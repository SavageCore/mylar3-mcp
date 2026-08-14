# mylar3-mcp

Part of the [arr-mcps](https://github.com/arr-mcps/arr-mcps) collection.
MCP server exposing [Mylar3](https://github.com/MylarComics/mylar3)'s HTTP API
as tools, so an LLM can read and manage your comic library: watchlist, wanted
issues, pull-list/upcoming, history, logs, story arcs, and providers.

Built with [FastMCP](https://gofastmcp.com).

## Enabling the API on your Mylar3 server

Mylar3's API is opt-in and disabled by default. You must enable it and obtain an
API key in Mylar's web UI (or bootstrap it with `cmd=getAPI` if HTTP basic auth
is configured). This is server-side configuration specific to how you run
Mylar3, and out of scope for this project - see Mylar3's own settings for
`API_ENABLED` and `API_KEY`.

## Install

Download a wheel from the [latest release](https://github.com/arr-mcps/mylar3-mcp/releases/latest)
and install it as a `uv` tool (no repo checkout needed):

```bash
uv tool install mylar3_mcp-*.whl
```

This puts a `mylar3-mcp` command on your PATH. Register it with Claude Code:

```bash
claude mcp add mylar3 \
  --env MYLAR_URL=http://your-mylar-host:8090 \
  --env MYLAR_API_KEY=<32-char key> \
  -- mylar3-mcp
```

### From source

```bash
uv sync
cp .env.example .env   # fill in MYLAR_URL and MYLAR_API_KEY
```

```bash
claude mcp add mylar3 \
  --env MYLAR_URL=http://your-mylar-host:8090 \
  --env MYLAR_API_KEY=<32-char key> \
  -- uv run --directory /path/to/mylar3-mcp mylar3-mcp
```

## Config

| Env var | Required | Default |
|---|---|---|
| `MYLAR_URL` | yes | - |
| `MYLAR_API_KEY` | yes (except `mylar_get_api`) | none (no `apikey` param sent) |
| `MYLAR_HTTP_ROOT` | no | `/` |

## Tools

**5 resource-scoped tools**, each covering multiple Mylar3 `?cmd=` API
commands (40 total) via an `operation` parameter. Reads use GET, writes use
POST. Call a tool with `operation` set to one of its listed commands and an
`arguments` dict matching that command's params — the tool's own description
(visible to your MCP client) lists every operation, its signature, and a
one-line doc.

| Tool | Operations | Covers |
|---|---|---|
| `mylar_comics` | 12 | Add/get/pause/resume/refresh/delete comics, book type, status, recheck files, index, find |
| `mylar_issues_queue` | 7 | Issue info, queue/unqueue, force search/process, regenerate covers, refresh seriesjson |
| `mylar_lists_discovery` | 7 | Read list, upcoming, wanted, story arcs, seriesjson listing, annual series |
| `mylar_providers` | 4 | List/add/change/delete providers |
| `mylar_system` | 10 | Version, API, history, logs, config, GitHub check, update, restart, shutdown |

Example: `mylar_comics(operation="mylar_del_comic", arguments={"id": "12345", "directory": True})`.
Command-level naming (`mylar_<verb>_<resource>`, matching the underlying
`?cmd=` API command) is preserved as the `operation` value:

| Operation | cmd |
|---|---|
| `mylar_get_index` | getIndex |
| `mylar_get_comic` | getComic |
| `mylar_get_comic_info` | getComicInfo |
| `mylar_get_issue_info` | getIssueInfo |
| `mylar_get_read_list` | getReadList |
| `mylar_get_upcoming` | getUpcoming |
| `mylar_get_wanted` | getWanted |
| `mylar_get_history` | getHistory |
| `mylar_get_logs` | getLogs |
| `mylar_find_comic` | findComic |
| `mylar_get_story_arc` | getStoryArc |
| `mylar_get_version` | getVersion |
| `mylar_list_providers` | listProviders |
| `mylar_seriesjson_listing` | seriesjsonListing |
| `mylar_list_annual_series` | listAnnualSeries |
| `mylar_get_api` | getAPI |
| `mylar_add_comic` | addComic |
| `mylar_pause_comic` | pauseComic |
| `mylar_resume_comic` | resumeComic |
| `mylar_refresh_comic` | refreshComic |
| `mylar_change_book_type` | changeBookType |
| `mylar_change_status` | changeStatus |
| `mylar_recheck_files` | recheckFiles |
| `mylar_queue_issue` | queueIssue |
| `mylar_unqueue_issue` | unqueueIssue |
| `mylar_regenerate_covers` | regenerateCovers |
| `mylar_refresh_seriesjson` | refreshSeriesjson |
| `mylar_add_story_arc` | addStoryArc |
| `mylar_force_search` | forceSearch |
| `mylar_force_process` | forceProcess |
| `mylar_add_provider` | addProvider |
| `mylar_change_provider` | changeProvider |
| `mylar_check_github` | checkGithub |
| `mylar_update` | update |
| `mylar_restart` | restart |
| `mylar_clear_logs` | clearLogs |
| `mylar_del_comic` | delComic (`directory=true` also deletes the folder from disk) |
| `mylar_del_provider` | delProvider |
| `mylar_shutdown` | shutdown (stops the server) |
| `mylar_set_config` | configUpdate (session-cookie auth, see AGENTS.md) |

## Notes

- Mylar3's API responses are inconsistently enveloped: some wrap in
  `{"success": true, "data": ...}`, some return the payload raw, and some
  return the bare string `"OK"`. The server unwraps all of these so tools
  return just the meaningful data.
- `mylar_queue_issue` and `mylar_force_search` can actually snatch/download
  issues - treat them as state-changing.
- Binary endpoints (`getArt`, `downloadIssue`, `downloadNZB`) are deliberately
  not exposed - they stream bytes, not JSON, which isn't useful over MCP.
- `id` params are ComicVine ComicIDs; issue IDs are separate. Bulk-capable
  cmds (`refreshComic`, `recheckFiles`, `regenerateCovers`, `refreshSeriesjson`)
  accept comma-separated lists or `all`/`missing`.

## Development

```bash
make help  # list all commands
```

| Command | Does |
|---|---|
| `make sync` | `uv sync` |
| `make test` | Offline tests - one per endpoint, mocked HTTP |
| `make test-integration` | Tests against the live instance (needs `MYLAR_URL`/`MYLAR_API_KEY`) |
| `make build` | Build wheel + sdist into `dist/` |
| `make bump-patch` / `bump-minor` / `bump-major` | Bump the version in `pyproject.toml` + `uv.lock` |
| `make clean` | Remove build artifacts |

The release workflow (`.github/workflows/release.yml`) builds and publishes to
[Releases](https://github.com/arr-mcps/mylar3-mcp/releases) whenever a `v*` tag
is pushed - so the usual flow is `make bump-patch`, commit, then tag and push.

The integration suite only reads data, plus a single reversible write test that
pauses and resumes an existing series (set via `MYLAR_TEST_COMIC_ID`) - it never
snatches, deletes, or modifies your library.
