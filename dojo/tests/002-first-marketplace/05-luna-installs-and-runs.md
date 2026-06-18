# 05 — Luna installs hello-world and the tool answers in chat

**Goal:** the full payoff — install from the live marketplace and use the tool.

## Preconditions
- Scenario 04 passed (marketplace added in Luna).

## Steps (real browser, Luna UI)
1. Click the **Marketplace** section in Luna's left pane.
2. See the remote plugin list fetched from `…/mp/official/index.json`; find
   `hello-world` (description + v0.1.0) with an **Install** button.
3. Click **Install**; approve the `plugin.install` approval card.
4. After install, the row flips to **Installed**.
5. Open **Settings → Plugins**; confirm `hello-world` is listed like any plugin
   with an enable/disable toggle.
6. In a chat, ask the agent to use the hello world tool (e.g. "use the hello
   world tool to greet Roy"). 

## Expected
- Install is approval-gated; core verifies the artifact sha256 before loading
  (a mismatch would refuse — see `luna/luna/plugins/install.py`).
- Marketplace row shows **Installed**; `hello-world` appears in Settings → Plugins.
- The `hello_world` tool runs and returns a greeting containing the provided
  name (e.g. "Hello, Roy! — from the marketplace").

## Pass/Fail
- PASS: install succeeds, badge flips, plugin appears in Plugins, tool answers.
- FAIL: install errors/hash refusal, badge never flips, plugin absent, or the
  tool doesn't run.

## Evidence
Screenshots: marketplace list, approval card, Installed badge, Plugins list,
chat turn with the tool result.

## (Optional) hello-world-2 from the dev marketplace
Repeat 04–05 using `https://luna-marketplaces.onrender.com/mp/dev-plugins/` and
`hello-world-2`, proving an uploaded (non-repo) plugin installs the same way.
