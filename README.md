# mylar3-mcp

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

Download a wheel from the [latest release](https://github.com/SavageCore/mylar3-mcp/releases/latest)
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

One tool per Mylar3 `?cmd=` API command. Reads use GET, writes use POST.

### Read-only

| Tool | cmd | Required params |
|---|---|---|
| `mylar_get_index` | getIndex | - |
| `mylar_get_comic` | getComic | id |
| `mylar_get_comic_info` | getComicInfo | id |
| `mylar_get_issue_info` | getIssueInfo | id |
| `mylar_get_read_list` | getReadList | - |
| `mylar_get_upcoming` | getUpcoming | - |
| `mylar_get_wanted` | getWanted | - |
| `mylar_get_history` | getHistory | - |
| `mylar_get_logs` | getLogs | - |
| `mylar_find_comic` | findComic | name |
| `mylar_get_story_arc` | getStoryArc | - |
| `mylar_get_version` | getVersion | - |
| `mylar_list_providers` | listProviders | - |
| `mylar_seriesjson_listing` | seriesjsonListing | - |
| `mylar_list_annual_series` | listAnnualSeries | list_issues or group_series |
| `mylar_get_api` | getAPI | username, password |

### Library / watchlist (mutating)

| Tool | cmd | Required params |
|---|---|---|
| `mylar_add_comic` | addComic | id |
| `mylar_pause_comic` | pauseComic | id |
| `mylar_resume_comic` | resumeComic | id |
| `mylar_refresh_comic` | refreshComic | id |
| `mylar_change_book_type` | changeBookType | id, booktype |
| `mylar_change_status` | changeStatus | status_from, status_to, id |
| `mylar_recheck_files` | recheckFiles | id |
| `mylar_queue_issue` | queueIssue | id |
| `mylar_unqueue_issue` | unqueueIssue | id |
| `mylar_regenerate_covers` | regenerateCovers | id |
| `mylar_refresh_seriesjson` | refreshSeriesjson | comicid |
| `mylar_add_story_arc` | addStoryArc | issues or arclist |
| `mylar_force_search` | forceSearch | - |
| `mylar_force_process` | forceProcess | nzb_name, nzb_folder |
| `mylar_add_provider` | addProvider | providertype, name, host, prov_apikey, enabled |
| `mylar_change_provider` | changeProvider | providertype, name or prov_id |
| `mylar_check_github` | checkGithub | - |
| `mylar_update` | update | - |
| `mylar_restart` | restart | - |
| `mylar_clear_logs` | clearLogs | - |

### Destructive

| Tool | cmd | Notes |
|---|---|---|
| `mylar_del_comic` | delComic | `directory=true` also deletes the folder from disk |
| `mylar_del_provider` | delProvider | removes a provider |
| `mylar_shutdown` | shutdown | stops the server |

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
[Releases](https://github.com/SavageCore/mylar3-mcp/releases) whenever a `v*` tag
is pushed - so the usual flow is `make bump-patch`, commit, then tag and push.

The integration suite only reads data, plus a single reversible write test that
pauses and resumes an existing series (set via `MYLAR_TEST_COMIC_ID`) - it never
snatches, deletes, or modifies your library.
