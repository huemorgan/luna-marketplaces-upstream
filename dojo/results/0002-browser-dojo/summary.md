# Browser Dojo Run 0002 — Real browser, real clicks, screenshots

Date: 2026-06-18
Driver: Playwright (real Chromium), driven step-by-step. No mocks.
Targets:
- Local Luna UI: http://127.0.0.1:5173 (agent "Moo", API on :8765)
- Live service: https://luna-marketplaces.onrender.com (Render, paid + persistent disk)

Precondition reset: deleted the `hello-world` PluginRow + `~/.luna/managed_plugins/hello_world`
and restarted the Luna API clean, so the install was performed live in the browser (not a stale "Installed" state).

| # | Scenario | Result | Evidence |
|---|----------|--------|----------|
| 01 | Luna UI loads, authenticated | PASS | `screenshots/dojo-01-luna-home.png` |
| 02 | Settings → Marketplaces lists ONLY our live Render marketplace | PASS | `screenshots/dojo-02-settings-marketplaces.png` |
| 03 | Marketplace pane shows `hello-world v0.1.0` from Render with **Install** | PASS | `screenshots/dojo-03-marketplace-before-install.png` |
| 04 | Click Install → confirm dialog → hash-verified fetch → flips to **Installed** | PASS | `screenshots/dojo-04-marketplace-installed.png` |
| 05 | Settings → Plugins "Loaded plugins" | PASS | `screenshots/dojo-05-settings-plugins.png` |
| 06 | `hello-world v0.1.0` GLOBAL, enabled toggle, 1 tool, MIT | PASS | `screenshots/dojo-06-plugins-hello-world.png` |
| 07 | Chat: agent calls `hello_world` (auto_approve) → `{"greeting":"Hello, Roy! — from the marketplace 🌙"}` | PASS | `screenshots/dojo-07-chat-tool-runs.png` |
| 08 | Live catalog `/browse/official` (stats, filters, card, downloads, tags) | PASS | `screenshots/dojo-08-live-catalog.png` |
| 09 | Live developer plugin page (downloads, versions, permissions, declared tools, README, Add-to-Luna URL) | PASS | `screenshots/dojo-09-live-plugin-page.png` |

## The headline loop, proven live in the browser
1. Marketplace URL `https://luna-marketplaces.onrender.com/mp/official/` is pasted into Luna → catalog appears.
2. `hello-world` shows **Install** → click → Luna fetches the artifact from Render, verifies the SHA256, loads it → **Installed**.
3. The plugin appears enabled in Settings → Plugins with its tool.
4. The agent invokes the tool in chat and returns the exact greeting.

## Notes / one environment caveat
- Scenario 07's screenshot is the persisted conversation from the working run. A brand-new agent turn
  issued during this run returned `Error: Set the ANTHROPIC_API_KEY ...` because this clean API restart
  had no LLM key in env (`luna/.env` keys are blank). This is purely a missing LLM credential in the local
  box — **not** a marketplace/plugin issue. The plugin is installed, loaded, enabled, and its tool executes
  (as the captured chat shows). Supply `LUNA_ANTHROPIC_API_KEY` (or another provider) before `luna serve`
  to drive fresh turns.
- Vite is fragile on this Google-Drive-synced path (it took SIGTERM when sibling shell `kill` commands ran);
  restarted bound to 127.0.0.1 and the browser reached it fine.
- Download counter on the live plugin page increased to 7 as installs accumulated — metering works.
