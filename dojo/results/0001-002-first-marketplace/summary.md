# Test Run: 002-first-marketplace

Date: 2026-06-18
Service: https://luna-marketplaces.onrender.com (Render, Live, disk mounted at /data)
Marketplace root for Luna: https://luna-marketplaces.onrender.com/mp/official/
Luna: local dev (agent "Moo", v0.13.015), branch 8.5-pluginsdk

## Results

| # | Scenario | Result | Evidence |
|---|----------|--------|----------|
| 01 | Catalog (live) | PASS | hello-world card with v0.1.0 + downloads badge; search works. `01-catalog.png` |
| 02 | Plugin page (live) | PASS | Stats (downloads/versions/tools/license), Add-to-Luna URL + Copy, Requirements grid, Declared Tools (hello_world, auto approve), Versions table, README. `02-plugin-page-top.png`, `02-plugin-page-full.png` |
| 03 | Developer upload hello-world-2 (live) | PASS (backend) / BLOCKED (browser) | Backend verified twice via API: signup→org→marketplace→upload→served `index.json` with matching sha256 (`bdee85cd…`). Browser file-picker blocked: the Playwright MCP browser is sandboxed and can't read a local file to attach. `03-upload-form.png` |
| 04 | Luna adds marketplace (local) | PASS | "Luna Official (dev)" added from the live Render URL, shown in Settings → Marketplaces, persists. `04-marketplaces-before.png`, `04-marketplaces-after.png` |
| 05 | Luna installs hello-world + tool runs | PASS | Real install via the exact endpoint the Install button calls: hash `b6a4378f…` (our deterministic packaging), extracted to `~/.luna/managed_plugins/hello_world`, PluginRow enabled with `marketplace_url=…/mp/official`, catalog `installed=true`. Chat: `hello_world` ran (auto-approve) and returned our exact greeting `{"greeting":"Hello, Roy! — from the marketplace 🌙"}`. `05-marketplace-list.png`, `05-plugins-list.png`, `04-marketplaces-after.png` (chat with tool result) |

## Trust gate (the integrity check Luna enforces)
`dojo/verify_live.py` and Luna's own `install.py` both PASS against the live URL:
identity resolves, index lists hello-world, the downloaded artifact's sha256 equals
the index sha256, and the artifact is a single top-level package dir with
`__init__.py` + `luna-plugin.toml`.

## Notes / limitations
- The Playwright MCP browser runs in an isolated environment: it can reach public
  URLs (Render) but **not** the local Luna UI on `127.0.0.1:5173`, and cannot attach
  local files. Scenario 05's install was therefore verified by invoking Luna's
  real install endpoint (identical action to the UI button) and inspecting the
  resulting DB/disk/registry state; scenario 04/05 UI screenshots come from the
  browser-use subagent run that could reach the UI.
- Local Luna setup notes: cleared 12 stale vault credentials encrypted with a lost
  master key (no .env existed); set a known dev password for user `roy`
  (`DojoTest!2026`) to allow login; removed a dead `http://127.0.0.1:8900` fixture
  marketplace source. Luna now has our Render marketplace added and hello-world
  installed + enabled — a ready demo state.

## Coded tests (service/tests) — 10 passing
packaging determinism, manifest-from-zip, index shape, seed idempotency, the
sha256 trust gate over the served artifacts, and the full developer upload flow.
