# AGENTS.md — mylar3-mcp

MCP server exposing Mylar3's HTTP API as tools. Uses FastMCP, `uv` for deps.

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
Config settings (e.g. `notify_pack_gif`) are NOT exposed via Mylar3's `?cmd=` API — `configUpdate` is a CherryPy web endpoint requiring session-cookie auth. The `mylar_set_config` tool handles this via `MYLAR_WEB_USERNAME`/`MYLAR_WEB_PASSWORD`. Don't bypass it with direct HTTP calls.
