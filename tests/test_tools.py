"""Offline tests: one per Mylar3 API command, plus envelope/error-path tests.

No network. Each tool call is checked against the exact HTTP request it should
produce (method, `cmd` query/form param, other params, apikey) via
httpx.MockTransport, using FastMCP's in-memory Client (see
https://gofastmcp.com/development/tests).
"""

import json
from urllib.parse import parse_qs

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError

import mylar_mcp


class Recorder:
    """Captures the single request made during a test and replays a canned response."""

    def __init__(self):
        self.method = None
        self.url = None
        self.headers = None
        self.body = None
        self.response = httpx.Response(200, json={"success": True, "data": {}})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.method = request.method
        self.url = request.url
        self.headers = request.headers
        self.body = request.content
        return self.response


@pytest.fixture
def recorder():
    return Recorder()


@pytest_asyncio.fixture
async def server(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = mylar_mcp.build_client("http://mylar.example.com", "test-key", transport=transport)
    monkeypatch.setattr(mylar_mcp, "_client", client)
    monkeypatch.setattr(mylar_mcp, "_API_KEY", "test-key")
    monkeypatch.setattr(mylar_mcp, "_HTTP_ROOT", "/")
    yield mylar_mcp.mcp
    await client.aclose()


async def call(server, tool_name, **kwargs):
    async with Client(server) as c:
        return await c.call_tool(tool_name, kwargs)


def params_of(recorder) -> dict:
    """Params as a plain str->str dict, from query string (GET) or form body (POST)."""
    if recorder.method == "GET":
        raw = recorder.url.query.decode()
    else:
        raw = recorder.body.decode() if recorder.body else ""
    return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}


def assert_cmd(recorder, cmd, method="GET", **expected):
    """Assert the request used `method`, targeted `cmd`, carried the apikey, and no more than expected params."""
    assert recorder.method == method
    p = params_of(recorder)
    assert p.pop("cmd", None) == cmd, f"expected cmd={cmd}, got {p}"
    assert p.pop("apikey", None) == "test-key"
    for k, v in expected.items():
        assert p.pop(k, None) == str(v), f"param {k}={v!r} not sent, got {p}"
    assert p == {}, f"unexpected extra params: {p}"


def raw(response, body):
    """Replay a raw JSON body (used for envelope tests)."""
    return httpx.Response(200, json=json.loads(body))


# --- one test per command ---------------------------------------------------

async def test_1_get_index(server, recorder):
    await call(server, "mylar_get_index")
    assert_cmd(recorder, "getIndex")


async def test_2_get_comic(server, recorder):
    await call(server, "mylar_get_comic", id="123")
    assert_cmd(recorder, "getComic", id="123")


async def test_3_get_comic_info(server, recorder):
    await call(server, "mylar_get_comic_info", id="123")
    assert_cmd(recorder, "getComicInfo", id="123")


async def test_4_get_issue_info(server, recorder):
    await call(server, "mylar_get_issue_info", id="456")
    assert_cmd(recorder, "getIssueInfo", id="456")


async def test_5_get_read_list(server, recorder):
    await call(server, "mylar_get_read_list")
    assert_cmd(recorder, "getReadList")


async def test_6_get_upcoming(server, recorder):
    await call(server, "mylar_get_upcoming")
    assert_cmd(recorder, "getUpcoming")


async def test_6b_get_upcoming_with_param(server, recorder):
    await call(server, "mylar_get_upcoming", include_downloaded_issues="Y")
    assert_cmd(recorder, "getUpcoming", include_downloaded_issues="Y")


async def test_7_get_wanted(server, recorder):
    await call(server, "mylar_get_wanted", story_arcs="true")
    assert_cmd(recorder, "getWanted", story_arcs="true")


async def test_8_get_history(server, recorder):
    await call(server, "mylar_get_history")
    assert_cmd(recorder, "getHistory")


async def test_9_get_logs(server, recorder):
    await call(server, "mylar_get_logs")
    assert_cmd(recorder, "getLogs")


async def test_10_find_comic(server, recorder):
    await call(server, "mylar_find_comic", name="Batman", mode="series")
    assert_cmd(recorder, "findComic", name="Batman", mode="series")


async def test_11_get_story_arc(server, recorder):
    await call(server, "mylar_get_story_arc")
    assert_cmd(recorder, "getStoryArc")


async def test_11b_get_story_arc_by_id(server, recorder):
    await call(server, "mylar_get_story_arc", id="999")
    assert_cmd(recorder, "getStoryArc", id="999")


async def test_12_get_version(server, recorder):
    await call(server, "mylar_get_version")
    assert_cmd(recorder, "getVersion")


async def test_13_list_providers(server, recorder):
    await call(server, "mylar_list_providers")
    assert_cmd(recorder, "listProviders")


async def test_14_seriesjson_listing(server, recorder):
    await call(server, "mylar_seriesjson_listing", missing="1")
    assert_cmd(recorder, "seriesjsonListing", missing="1")


async def test_15_list_annual_series(server, recorder):
    await call(server, "mylar_list_annual_series", list_issues="1")
    assert_cmd(recorder, "listAnnualSeries", list_issues="1")


async def test_16_get_api(server, recorder):
    await call(server, "mylar_get_api", username="bob", password="pw")
    assert_cmd(recorder, "getAPI", username="bob", password="pw")


# --- mutating (POST) ---------------------------------------------------------

async def test_17_add_comic(server, recorder):
    await call(server, "mylar_add_comic", id="123")
    assert_cmd(recorder, "addComic", "POST", id="123")


async def test_18_pause_comic(server, recorder):
    await call(server, "mylar_pause_comic", id="123")
    assert_cmd(recorder, "pauseComic", "POST", id="123")


async def test_19_resume_comic(server, recorder):
    await call(server, "mylar_resume_comic", id="123")
    assert_cmd(recorder, "resumeComic", "POST", id="123")


async def test_20_refresh_comic(server, recorder):
    await call(server, "mylar_refresh_comic", id="123,456")
    assert_cmd(recorder, "refreshComic", "POST", id="123,456")


async def test_21_change_book_type(server, recorder):
    await call(server, "mylar_change_book_type", id="123", booktype="TPB")
    assert_cmd(recorder, "changeBookType", "POST", id="123", booktype="TPB")


async def test_22_change_status(server, recorder):
    await call(server, "mylar_change_status", status_from="Wanted", status_to="Downloaded", id="123")
    assert_cmd(recorder, "changeStatus", "POST", status_from="Wanted", status_to="Downloaded", id="123")


async def test_23_recheck_files(server, recorder):
    await call(server, "mylar_recheck_files", id="123")
    assert_cmd(recorder, "recheckFiles", "POST", id="123")


async def test_24_queue_issue(server, recorder):
    await call(server, "mylar_queue_issue", id="456")
    assert_cmd(recorder, "queueIssue", "POST", id="456")


async def test_25_unqueue_issue(server, recorder):
    await call(server, "mylar_unqueue_issue", id="456")
    assert_cmd(recorder, "unqueueIssue", "POST", id="456")


async def test_26_regenerate_covers(server, recorder):
    await call(server, "mylar_regenerate_covers", id="all")
    assert_cmd(recorder, "regenerateCovers", "POST", id="all")


async def test_27_refresh_seriesjson(server, recorder):
    await call(server, "mylar_refresh_seriesjson", comicid="123")
    assert_cmd(recorder, "refreshSeriesjson", "POST", comicid="123")


async def test_28_add_story_arc(server, recorder):
    await call(server, "mylar_add_story_arc", issues="1,2,3", storyarcname="Crisis")
    assert_cmd(recorder, "addStoryArc", "POST", issues="1,2,3", storyarcname="Crisis")


async def test_29_force_search(server, recorder):
    await call(server, "mylar_force_search")
    assert_cmd(recorder, "forceSearch", "POST")


async def test_30_force_process(server, recorder):
    await call(server, "mylar_force_process", nzb_name="x.nzb", nzb_folder="/data")
    assert_cmd(recorder, "forceProcess", "POST", nzb_name="x.nzb", nzb_folder="/data")


async def test_31_add_provider(server, recorder):
    await call(server, "mylar_add_provider", providertype="newznab", name="n", host="h", prov_apikey="k", enabled="1")
    assert_cmd(recorder, "addProvider", "POST", providertype="newznab", name="n", host="h", prov_apikey="k", enabled="1")


async def test_32_change_provider(server, recorder):
    await call(server, "mylar_change_provider", providertype="newznab", name="n", host="h2")
    assert_cmd(recorder, "changeProvider", "POST", providertype="newznab", name="n", host="h2")


async def test_33_check_github(server, recorder):
    await call(server, "mylar_check_github")
    assert_cmd(recorder, "checkGithub", "POST")


async def test_34_update(server, recorder):
    await call(server, "mylar_update")
    assert_cmd(recorder, "update", "POST")


async def test_35_restart(server, recorder):
    await call(server, "mylar_restart")
    assert_cmd(recorder, "restart", "POST")


async def test_36_clear_logs(server, recorder):
    await call(server, "mylar_clear_logs")
    assert_cmd(recorder, "clearLogs", "POST")


# --- destructive (POST) -------------------------------------------------------

async def test_37_del_comic(server, recorder):
    await call(server, "mylar_del_comic", id="123", directory="true")
    assert_cmd(recorder, "delComic", "POST", id="123", directory="true")


async def test_38_del_provider(server, recorder):
    await call(server, "mylar_del_provider", providertype="newznab", name="n")
    assert_cmd(recorder, "delProvider", "POST", providertype="newznab", name="n")


async def test_39_shutdown(server, recorder):
    await call(server, "mylar_shutdown")
    assert_cmd(recorder, "shutdown", "POST")


# --- http_root ----------------------------------------------------------------

async def test_http_root_in_base_url(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = mylar_mcp.build_client("http://mylar.example.com", "test-key", http_root="/mylar", transport=transport)
    monkeypatch.setattr(mylar_mcp, "_client", client)
    monkeypatch.setattr(mylar_mcp, "_API_KEY", "test-key")
    await call(mylar_mcp.mcp, "mylar_get_index")
    assert recorder.url.path.rstrip("/") == "/mylar/api"
    assert_cmd(recorder, "getIndex")
    await client.aclose()


# --- auth / apikey ------------------------------------------------------------

async def test_no_apikey_means_no_apikey_param(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = mylar_mcp.build_client("http://mylar.example.com", None, transport=transport)
    monkeypatch.setattr(mylar_mcp, "_client", client)
    monkeypatch.setattr(mylar_mcp, "_API_KEY", None)
    await call(mylar_mcp.mcp, "mylar_get_version")
    p = params_of(recorder)
    assert p.pop("cmd", None) == "getVersion"
    assert "apikey" not in p
    await client.aclose()


# --- envelope / error paths -----------------------------------------------------

async def test_envelope_unwraps_data(server, recorder):
    recorder.response = httpx.Response(200, json={"success": True, "data": {"current_version": "0.7.0"}})
    result = await call(server, "mylar_get_version")
    assert result.data == {"current_version": "0.7.0"}


async def test_raw_payload_returned_without_envelope(server, recorder):
    recorder.response = httpx.Response(200, json=[{"id": "123", "name": "Batman"}])
    result = await call(server, "mylar_get_index")
    assert result.data == [{"id": "123", "name": "Batman"}]


async def test_bare_ok_string_returned(server, recorder):
    recorder.response = httpx.Response(200, json="OK")
    result = await call(server, "mylar_pause_comic", id="123")
    assert result.data == {"message": "OK"}


async def test_success_false_raises_with_message(server, recorder):
    recorder.response = httpx.Response(200, json={"success": False, "error": {"code": 461, "message": "Unknown command"}})
    with pytest.raises(ToolError, match="Unknown command"):
        await call(server, "mylar_get_index")


async def test_401_api_disabled_message(server, recorder):
    recorder.response = httpx.Response(401, json={"success": False, "error": {"code": 460, "message": "API not enabled. Set API_ENABLED=True"}})
    with pytest.raises(ToolError, match="API not enabled"):
        await call(server, "mylar_get_index")


async def test_non_json_error_body_does_not_crash(server, recorder):
    recorder.response = httpx.Response(502, text="<html>Bad Gateway</html>")
    with pytest.raises(ToolError, match="502"):
        await call(server, "mylar_get_index")


async def test_non_json_success_body_is_tolerated(server, recorder):
    recorder.response = httpx.Response(200, text="not json")
    result = await call(server, "mylar_get_index")
    assert result.data == {"message": "not json"}


async def test_non_json_empty_success_body_is_tolerated(server, recorder):
    recorder.response = httpx.Response(200, text="")
    result = await call(server, "mylar_get_index")
    assert result.data == {"message": "OK (HTTP 200)"}


# --- main() --------------------------------------------------------------------

def test_main_requires_mylar_url(monkeypatch):
    monkeypatch.delenv("MYLAR_URL", raising=False)
    with pytest.raises(SystemExit):
        mylar_mcp.main()
