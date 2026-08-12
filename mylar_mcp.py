"""MCP server exposing Mylar3's HTTP API (https://github.com/MylarComics/mylar3) as tools.

Mylar3 is CherryPy-based and dispatches everything through a single ``?cmd=``
endpoint rooted at ``<base_url><http_root>/api``. Auth is a 32-char API key
passed as the ``apikey`` query (or form) parameter -- the only auth mode the
classic API uses (``/rest`` uses an ``Api-Key`` header but is experimental and
skeletal, so it is not surfaced here).

Design notes vs. Dashy's MCP server:

* Mylar's responses are NOT uniformly enveloped. Some cmds return
  ``{"success": true, "data": ...}``, some return the payload raw, and some
  return the bare JSON string ``"OK"``. ``_unwrap`` handles all three.
* Reads use GET, mutations use POST, matching what the Mylar web UI does.
* Binary endpoints (getArt, downloadIssue, downloadNZB) stream bytes, not JSON,
  and are deliberately excluded -- an LLM should not tunnel binary over MCP.
"""

import os
import sys
from typing import Any
from urllib.parse import urlencode

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

DESTRUCTIVE = ToolAnnotations(destructiveHint=True)

# Mylar responses are plain JSON but the envelope is inconsistent (see module
# docstring). FastMCP needs a concrete schema to build structured content and
# skips that step for a bare `Any` return type, so use explicit `dict[str, Any]`
# where the payload is an object.
JSONObj = dict[str, Any]
JSONVal = JSONObj | list[Any]

mcp = FastMCP("mylar3-mcp")

_client: httpx.AsyncClient | None = None
_API_KEY: str | None = None
_HTTP_ROOT = "/"
_web_client: httpx.AsyncClient | None = None
_web_transport: httpx.BaseTransport | None = None
_WEB_USERNAME: str | None = None
_WEB_PASSWORD: str | None = None


def build_client(
    base_url: str, api_key: str | None, http_root: str = "/", transport: httpx.BaseTransport | None = None
) -> httpx.AsyncClient:
    """Build an httpx client rooted at the Mylar API.

    Mylar's auth is the ``apikey`` query param (sent per-request by ``_req``),
    so no default header is set here -- the base URL just carries the /api path.
    """
    root = http_root if http_root.startswith("/") else f"/{http_root}"
    return httpx.AsyncClient(base_url=f"{base_url.rstrip('/')}{root.rstrip('/')}/api", transport=transport)


def _unwrap(r: httpx.Response) -> Any:
    """Normalise a Mylar response body into just the meaningful payload.

    Some commands (restart, shutdown, several void mutations) answer a 2xx with
    an empty or plain-text body rather than JSON. Treat those as success instead
    of failing, so tools like ``mylar_restart`` don't error out mid-restart.
    """
    try:
        j = r.json()
    except ValueError:
        if r.status_code < 400:
            return {"message": r.text.strip() or f"OK (HTTP {r.status_code})"}
        raise ToolError(f"Mylar API {r.status_code}: non-JSON response")

    if isinstance(j, dict) and "success" in j:
        if not j["success"]:
            err = j.get("error", {}) if isinstance(j.get("error"), dict) else {}
            code = err.get("code", "?")
            msg = err.get("message", "unknown error")
            raise ToolError(f"Mylar API {code}: {msg}")
        return j.get("data")

    # Mylar's void mutations return the bare JSON string "OK" (or similar).
    # FastMCP needs structured content to be a dict, so wrap it.
    if isinstance(j, str):
        return {"message": j}

    return j


def _obj(value: Any) -> JSONObj:
    """Normalise a Mylar payload into a dict for FastMCP's structured content.

    FastMCP requires structured content to be a dict, but some single-entity
    Mylar endpoints (getComic, getComicInfo, getIssueInfo) answer with a
    one-element list. Unwrap that to the bare dict; wrap anything else.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return {"data": value}


async def _req(cmd: str, params: dict[str, Any] | None = None, *, read_only: bool = True) -> Any:
    assert _client is not None, "client not configured"
    body = {"cmd": cmd, **(params or {})}
    if _API_KEY:
        body["apikey"] = _API_KEY
    method = "GET" if read_only else "POST"

    if method == "GET":
        r = await _client.request(method, "", params=body)
    else:
        r = await _client.request(method, "", content=urlencode(body), headers={"Content-Type": "application/x-www-form-urlencoded"})

    if r.status_code >= 400:
        try:
            j = r.json()
            if isinstance(j, dict) and "success" in j and not j["success"]:
                err = j.get("error", {}) if isinstance(j.get("error"), dict) else {}
                msg = err.get("message", r.text)
            else:
                msg = j.get("message", r.text)
        except ValueError:
            msg = r.text
        raise ToolError(f"Mylar API {r.status_code}: {msg}")
    return _unwrap(r)


async def _web_login() -> httpx.AsyncClient:
    """Authenticate against the CherryPy web UI and return a cookie-bearing
    client. Config settings are only writable via the web ``configUpdate``
    endpoint (session-cookie auth), not the ``?cmd=`` API, so this is required
    for ``mylar_set_config``. Uses MYLAR_URL + MYLAR_WEB_USERNAME +
    MYLAR_WEB_PASSWORD."""
    global _web_client
    if _web_client is not None:
        return _web_client
    if _WEB_USERNAME is None or _WEB_PASSWORD is None:
        raise ToolError(
            "MYLAR_WEB_USERNAME and MYLAR_WEB_PASSWORD are required for config "
            "changes (configUpdate uses session auth, not the API key)"
        )
    base = os.environ.get("MYLAR_URL", "")
    root = _HTTP_ROOT if _HTTP_ROOT.startswith("/") else f"/{_HTTP_ROOT}"
    client = httpx.AsyncClient(
        base_url=f"{base.rstrip('/')}{root}",
        follow_redirects=True,
        transport=_web_transport,
    )
    r = await client.post(
        "/auth/login",
        data={
            "current_username": _WEB_USERNAME,
            "current_password": _WEB_PASSWORD,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status_code >= 400:
        raise ToolError(f"Mylar web login failed: HTTP {r.status_code}")
    _web_client = client
    return client


async def _web_config_update(values: dict[str, Any]) -> dict[str, Any]:
    """POST settings to the web configUpdate endpoint using a session cookie."""
    client = await _web_login()
    r = await client.post(
        "/configUpdate",
        data=values,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status_code >= 400:
        raise ToolError(f"Mylar configUpdate failed: HTTP {r.status_code}")
    return {"message": "config updated", "status": r.status_code}



# --- read-only tools ---------------------------------------------------------


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_index() -> JSONVal:
    """List every series on the Mylar3 watchlist (id, name, status, publisher, etc.)."""
    return await _req("getIndex")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_comic(id: str) -> JSONObj:
    """Get one series and its issues: returns {comic, issues, annuals}. `id` is the ComicVine ComicID."""
    return _obj(await _req("getComic", {"id": id}))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_comic_info(id: str) -> JSONObj:
    """Get a single series row from the comics table. `id` is the ComicVine ComicID."""
    return _obj(await _req("getComicInfo", {"id": id}))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_issue_info(id: str) -> JSONObj:
    """Get a single issue row from the issues table. `id` is the IssueID."""
    return _obj(await _req("getIssueInfo", {"id": id}))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_read_list() -> JSONVal:
    """List the issues in the read list, ordered by issue date."""
    return await _req("getReadList")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_upcoming(include_downloaded_issues: str | None = None) -> JSONVal:
    """List this week's wanted issues. Pass include_downloaded_issues='Y' to also include Snatched/Downloaded."""
    params = {}
    if include_downloaded_issues:
        params["include_downloaded_issues"] = include_downloaded_issues
    return await _req("getUpcoming", params)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_wanted(story_arcs: str | None = None) -> JSONVal:
    """List wanted issues. Pass story_arcs='true' to also include Wanted story-arc issues and annuals."""
    params = {}
    if story_arcs:
        params["story_arcs"] = story_arcs
    return await _req("getWanted", params)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_history() -> JSONVal:
    """List rows from the snatched table (download history), newest first."""
    return await _req("getHistory")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_logs() -> JSONVal:
    """Return Mylar3's in-memory log buffer."""
    return await _req("getLogs")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_find_comic(
    name: str,
    issue: str | None = None,
    type_: str | None = None,
    mode: str | None = None,
    page: str | None = None,
    pageSize: str | None = None,
    serinfo: str | None = None,
) -> JSONVal:
    """Search ComicVine for a series. `name` is required; type_='story_arc' searches arcs, mode can be series/pullseries/want."""
    params: dict[str, Any] = {"name": name}
    if issue:
        params["issue"] = issue
    if type_:
        params["type_"] = type_
    if mode:
        params["mode"] = mode
    if page:
        params["page"] = page
    if pageSize:
        params["pageSize"] = pageSize
    if serinfo:
        params["serinfo"] = serinfo
    return await _req("findComic", params)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_story_arc(id: str | None = None, customOnly: str | None = None) -> JSONVal:
    """List story arcs; with `id`, list that arc's issues in reading order. Pass customOnly='1' for custom arcs only."""
    params = {}
    if id:
        params["id"] = id
    if customOnly:
        params["customOnly"] = customOnly
    return await _req("getStoryArc", params)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_version() -> JSONObj:
    """Get Mylar3 version info: git_path, install_type, current_version, latest_version, commits_behind."""
    return await _req("getVersion")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_list_providers() -> JSONObj:
    """List configured newznab/torznab providers: returns {newznabs: [...], torznabs: [...]}."""
    return await _req("listProviders")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_seriesjson_listing(missing: str | None = None) -> JSONVal:
    """List series with/without series.json. Pass missing='1' for only series missing a series.json."""
    params = {}
    if missing:
        params["missing"] = missing
    return await _req("seriesjsonListing", params)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_list_annual_series(
    list_issues: str | None = None, group_series: str | None = None, show_downloaded: str | None = None
) -> JSONVal:
    """List annual issues. Provide list_issues OR group_series; pass show_downloaded to include downloaded."""
    params: dict[str, Any] = {}
    if list_issues:
        params["list_issues"] = list_issues
    if group_series:
        params["group_series"] = group_series
    if show_downloaded:
        params["show_downloaded"] = show_downloaded
    return await _req("listAnnualSeries", params)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def mylar_get_api(username: str, password: str) -> JSONObj:
    """Bootstrap helper: fetch the API key using HTTP basic login credentials. Does not require MYLAR_API_KEY."""
    return await _req("getAPI", {"username": username, "password": password})


# --- mutating tools (recoverable) -------------------------------------------


@mcp.tool
async def mylar_add_comic(id: str) -> JSONObj:
    """Queue adding a series to the watchlist by ComicVine ComicID. Runs in a background thread."""
    return await _req("addComic", {"id": id}, read_only=False)


@mcp.tool
async def mylar_pause_comic(id: str) -> JSONObj:
    """Pause a series' wanted tracking. `id` is the ComicVine ComicID."""
    return await _req("pauseComic", {"id": id}, read_only=False)


@mcp.tool
async def mylar_resume_comic(id: str) -> JSONObj:
    """Resume a paused series. `id` is the ComicVine ComicID."""
    return await _req("resumeComic", {"id": id}, read_only=False)


@mcp.tool
async def mylar_refresh_comic(id: str) -> JSONObj:
    """Queue a ComicVine refresh of a series. `id` accepts a single id or comma-separated list."""
    return await _req("refreshComic", {"id": id}, read_only=False)


@mcp.tool
async def mylar_change_book_type(id: str, booktype: str) -> JSONObj:
    """Force a series' book type. `booktype`: Print, Digital, TPB, GN, HC, or One-Shot."""
    return await _req("changeBookType", {"id": id, "booktype": booktype}, read_only=False)


@mcp.tool
async def mylar_change_status(status_from: str, status_to: str, id: str) -> JSONObj:
    """Bulk-change issue status across a series. Pass id='all' for every series. status_from/status_to are issue statuses."""
    return await _req("changeStatus", {"status_from": status_from, "status_to": status_to, "id": id}, read_only=False)


@mcp.tool
async def mylar_recheck_files(id: str) -> JSONObj:
    """Recheck files on disk for a series. `id` accepts a single id, comma-list, or a JSON array."""
    return await _req("recheckFiles", {"id": id}, read_only=False)


@mcp.tool
async def mylar_queue_issue(id: str) -> JSONObj:
    """Mark an issue Wanted and immediately kick off a search (may snatch/download). `id` is the IssueID."""
    return await _req("queueIssue", {"id": id}, read_only=False)


@mcp.tool
async def mylar_unqueue_issue(id: str) -> JSONObj:
    """Mark an issue Skipped (un-queue it). `id` is the IssueID."""
    return await _req("unqueueIssue", {"id": id}, read_only=False)


@mcp.tool
async def mylar_regenerate_covers(id: str, overwrite_existing: str | None = None) -> JSONObj:
    """Re-fetch series cover images. `id`: single, comma-list, 'all', or 'missing'."""
    params: dict[str, Any] = {"id": id}
    if overwrite_existing:
        params["overwrite_existing"] = overwrite_existing
    return await _req("regenerateCovers", params, read_only=False)


@mcp.tool
async def mylar_refresh_seriesjson(comicid: str) -> JSONObj:
    """Regenerate series.json files. `comicid`: single, list, 'all', 'missing', or 'refresh-missing'."""
    return await _req("refreshSeriesjson", {"comicid": comicid}, read_only=False)


@mcp.tool
async def mylar_add_story_arc(
    issues: str | None = None, arclist: str | None = None, id: str | None = None, storyarcname: str | None = None
) -> JSONObj:
    """Add/create a story arc. Provide `issues` OR `arclist`. `storyarcname` required when creating; `id` to extend an existing arc."""
    params: dict[str, Any] = {}
    if issues:
        params["issues"] = issues
    if arclist:
        params["arclist"] = arclist
    if id:
        params["id"] = id
    if storyarcname:
        params["storyarcname"] = storyarcname
    return await _req("addStoryArc", params, read_only=False)


@mcp.tool
async def mylar_force_search() -> JSONObj:
    """Trigger a wanted-issue search across the library. May snatch/download wanted issues. Runs in-process."""
    return await _req("forceSearch", read_only=False)


@mcp.tool
async def mylar_force_process(
    nzb_name: str,
    nzb_folder: str,
    failed: str | None = None,
    issueid: str | None = None,
    comicid: str | None = None,
    ddl: str | None = None,
    oneoff: str | None = None,
    apc_version: str | None = None,
    comicrn_version: str | None = None,
) -> JSONObj:
    """Enqueue a post-processing job. Requires nzb_name and nzb_folder. Used by SABnzbd/NZBGet-style callbacks."""
    params: dict[str, Any] = {"nzb_name": nzb_name, "nzb_folder": nzb_folder}
    if failed:
        params["failed"] = failed
    if issueid:
        params["issueid"] = issueid
    if comicid:
        params["comicid"] = comicid
    if ddl:
        params["ddl"] = ddl
    if oneoff:
        params["oneoff"] = oneoff
    if apc_version:
        params["apc_version"] = apc_version
    if comicrn_version:
        params["comicrn_version"] = comicrn_version
    return await _req("forceProcess", params, read_only=False)


@mcp.tool
async def mylar_add_provider(
    providertype: str, name: str, host: str, prov_apikey: str, enabled: str, categories: str | None = None, uid: str | None = None
) -> JSONObj:
    """Add a newznab or torznab provider. providertype is 'newznab' or 'torznab' (torznab requires categories)."""
    params: dict[str, Any] = {
        "providertype": providertype,
        "name": name,
        "host": host,
        "prov_apikey": prov_apikey,
        "enabled": enabled,
    }
    if categories:
        params["categories"] = categories
    if uid:
        params["uid"] = uid
    return await _req("addProvider", params, read_only=False)


@mcp.tool
async def mylar_change_provider(
    providertype: str,
    name: str | None = None,
    prov_id: str | None = None,
    altername: str | None = None,
    host: str | None = None,
    prov_apikey: str | None = None,
    enabled: str | None = None,
    categories: str | None = None,
    uid: str | None = None,
) -> JSONObj:
    """Modify a provider. Provide providertype and either `name` or `prov_id`, plus any fields to change."""
    params: dict[str, Any] = {"providertype": providertype}
    if name:
        params["name"] = name
    if prov_id:
        params["prov_id"] = prov_id
    if altername:
        params["altername"] = altername
    if host:
        params["host"] = host
    if prov_apikey:
        params["prov_apikey"] = prov_apikey
    if enabled:
        params["enabled"] = enabled
    if categories:
        params["categories"] = categories
    if uid:
        params["uid"] = uid
    return await _req("changeProvider", params, read_only=False)


@mcp.tool
async def mylar_check_github() -> JSONObj:
    """Check GitHub for updates and return current version data."""
    return await _req("checkGithub", read_only=False)


@mcp.tool
async def mylar_update() -> JSONObj:
    """Trigger Mylar3 to self-update (may restart the app)."""
    return await _req("update", read_only=False)


@mcp.tool
async def mylar_restart() -> JSONObj:
    """Restart Mylar3."""
    return await _req("restart", read_only=False)


@mcp.tool
async def mylar_clear_logs() -> JSONObj:
    """Clear Mylar3's in-memory log buffer."""
    return await _req("clearLogs", read_only=False)


# --- config / destructive tools ---------------------------------------------


@mcp.tool
async def mylar_set_config(settings: dict[str, Any]) -> JSONObj:
    """Set one or more Mylar config options via the web configUpdate endpoint.

    Takes a dict of checkbox/text settings keyed by their config.ini name
    (e.g. {"notify_pack_gif": True}). Checkboxes use boolean values; unchecked
    checkboxes should be set to False. Requires MYLAR_WEB_USERNAME and
    MYLAR_WEB_PASSWORD. Applies immediately and persists to config.ini.
    """
    values: dict[str, Any] = {}
    for k, v in settings.items():
        if isinstance(v, bool):
            values[k] = "True" if v else "False"
        elif v is None:
            values[k] = "False"
        else:
            values[k] = str(v)
    return await _web_config_update(values)


@mcp.tool(annotations=DESTRUCTIVE)
async def mylar_del_comic(id: str, directory: str | None = None) -> JSONObj:
    """Delete a series from the watchlist (and its issues). `id` is the ComicVine ComicID.
    WARNING: pass directory='true' to also delete the comic folder from disk (rmtree)."""
    params: dict[str, Any] = {"id": id}
    if directory:
        params["directory"] = directory
    return await _req("delComic", params, read_only=False)


@mcp.tool(annotations=DESTRUCTIVE)
async def mylar_del_provider(providertype: str, name: str | None = None, prov_id: str | None = None) -> JSONObj:
    """Remove a provider. Provide providertype and either `name` or `prov_id`."""
    params: dict[str, Any] = {"providertype": providertype}
    if name:
        params["name"] = name
    if prov_id:
        params["prov_id"] = prov_id
    return await _req("delProvider", params, read_only=False)


@mcp.tool(annotations=DESTRUCTIVE)
async def mylar_shutdown() -> JSONObj:
    """Shut down Mylar3. This stops the server."""
    return await _req("shutdown", read_only=False)


def main() -> None:
    global _client, _API_KEY, _HTTP_ROOT, _WEB_USERNAME, _WEB_PASSWORD
    url = os.environ.get("MYLAR_URL")
    if not url:
        print("MYLAR_URL environment variable is required (e.g. http://mylar.local:8090)", file=sys.stderr)
        raise SystemExit(1)
    _API_KEY = os.environ.get("MYLAR_API_KEY")
    _HTTP_ROOT = os.environ.get("MYLAR_HTTP_ROOT", "/")
    _WEB_USERNAME = os.environ.get("MYLAR_WEB_USERNAME")
    _WEB_PASSWORD = os.environ.get("MYLAR_WEB_PASSWORD")
    _client = build_client(url, _API_KEY, _HTTP_ROOT)
    mcp.run()


if __name__ == "__main__":
    main()
