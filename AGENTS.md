# AGENTS.md — mylar3-mcp

MCP server exposing Mylar3's HTTP API as tools. Uses FastMCP, `uv` for deps.

Exposed as **5 resource-scoped portmanteau tools**, not one tool per command — see "Portmanteau registration" below. A prior version registered all 40 commands individually; that blew the MCP context budget (~40 tools × ~250 tokens ≈ 10k tokens just for this one server) and has been retired.

## Testing
- Offline suite: `make test` (or `uv run pytest`)
- Live integration (needs `MYLAR_URL`/`MYLAR_API_KEY`): `make test-integration`

## Release workflow
Always use the `make bump-*` targets to bump the version (`uv version --bump patch|minor|major`), which updates `pyproject.toml` and `uv.lock` together. Do NOT edit the version by hand.

- Bump: `make bump-patch` (or `bump-minor` / `bump-major`)
- Commit message is **just the version**, e.g. `0.1.2` — nothing else.
- Tag it `v<version>` (e.g. `v0.1.2`).
- Push main and the tag:
  ```
  git push origin main
  git push origin v<version>
  ```
- Then sync the project copy:
  ```
  cd /home/savagecore/Documents/christopfarr/mcp/mylar3-mcp
  git fetch origin && git reset --hard origin/main
  ```
- Deploy to the Proxmox host (root SSH key): pull the repo then reinstall the uv tool:
  ```
  ssh root@192.168.50.3 -- 'cd /root/mylar3-mcp && git fetch origin && git reset --hard origin/main'
  ssh root@192.168.50.3 -- 'cd /root/mylar3-mcp && uv tool install --force .'
  ```
  The host runs it via `uv tool install` → `/root/.local/bin/mylar3-mcp` (not from the repo).

## Config settings note
Config settings (e.g. `notify_pack_gif`) are NOT exposed via Mylar3's `?cmd=` API — `configUpdate` is a CherryPy web endpoint requiring session-cookie auth. The `mylar_set_config` operation (in the `mylar_system` group) handles this via `MYLAR_WEB_USERNAME`/`MYLAR_WEB_PASSWORD`. Don't bypass it with direct HTTP calls.

## Portmanteau registration — **do not go back to one tool per command**
- `_GROUPS` near the bottom of `mylar_mcp.py` buckets every command function into one of 5 resource groups (`mylar_comics`, `mylar_issues_queue`, `mylar_lists_discovery`, `mylar_providers`, `mylar_system`). `_register_tools()` registers exactly one MCP tool per group via `_register_group`, which wraps the group's functions in a single `dispatch(operation, arguments)` closure. The command functions themselves are unchanged — they're plain callables looked up by name via `globals()`, not separately-registered tools.
- `operation` is typed `Literal[<the group's function names>]`, so FastMCP/pydantic validates it against the real operation list before `dispatch` ever runs — an invalid operation never reaches the group tool's body.
- Adding a new command: write the function as before (no decorator), then add its name to exactly one group in `_GROUPS`. `tests/test_tools.py::test_all_operations_grouped` fails if a name doesn't resolve to a real module attribute.
- New resource area big enough to need its own group (rare): add a new `_GROUPS` key. Keep the total group count at or under ~15 — that ceiling is the entire point of this pattern.
- If you're tempted to add a per-command `@mcp.tool` decorator back, don't — every command must be reachable only via its group's `operation` enum. A 40-tool server (one per command) previously cost ~10k tokens of system-prompt budget on every session start; the 5-tool grouped version costs roughly a tenth of that.
- Annotations: a group tool is `readOnlyHint=True` (`READONLY`) only when *every* operation in it was originally read-only (tracked in `_register_tools()`'s `readonly_names` set, built from both the `annotations=READONLY` constant style and the inline `annotations=ToolAnnotations(readOnlyHint=True)` style the read-only section used). None of the 5 groups end up all-read-only, since each mixes at least one write.
