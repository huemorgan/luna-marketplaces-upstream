# 04 — Luna adds the marketplace by URL

**Goal:** an owner pastes our live marketplace URL into Luna and it is accepted,
with the marketplace identity resolved.

## Preconditions
- Luna running locally (UI `http://localhost:5173`, API `http://127.0.0.1:8765`),
  post-onboarding. `plugin_marketplace` plugin enabled.

## Steps (real browser, Luna UI)
1. Open Luna → **Settings → Marketplaces**.
2. Paste `https://luna-marketplaces.onrender.com/mp/official/` and click **Add**.
3. Observe the marketplace row.

## Expected
- The marketplace is added and shows its name **Luna Official (dev)** (read from
  `.well-known/luna-marketplace.json`).
- A **Marketplace** section appears in the left pane.
- No error toast; the URL persists across a page reload.

## Pass/Fail
- PASS: marketplace added, named correctly, persists.
- FAIL: add errors, wrong/blank name, or it disappears on reload.

## Evidence
Screenshots: Marketplaces tab before/after add, left-pane Marketplace section.
