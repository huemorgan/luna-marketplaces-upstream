# Dojo — Plan 002: First Marketplace (end-to-end)

Conversation/browser test scenarios proving the whole loop from
`plan/002-first-marketplace/PLAN.md`: a live Render marketplace serves a
repo-owned `hello-world` plugin in the Luna-v0 protocol; a developer can upload
`hello-world-2` through the service; and a real Luna agent adds the marketplace
URL, installs both, and runs their tools.

These are LLM-driven browser tests (see `luna/dojo/vision/vision.md`): read the
DOM, take screenshots, judge behavior — not coded assertions. Coded
unit/integration tests live in `service/tests/`.

## Surfaces under test
- **Service (live):** `https://luna-marketplaces.onrender.com`
  - Marketplace root for Luna: `https://luna-marketplaces.onrender.com/mp/official/`
  - Catalog UI: `/browse/official`  · Plugin page: `/browse/official/plugin/hello-world`
  - Management SPA: `/app`
- **Luna (local dev):** UI `http://localhost:5173`, API `http://127.0.0.1:8765`

## Scenarios
| # | File | Proves |
|---|------|--------|
| 01 | `01-service-serves-protocol.md` | Live service serves identity + index + artifact; hash matches |
| 02 | `02-catalog-and-plugin-page.md` | Browsable catalog + developer plugin page (downloads, versions, perms) |
| 03 | `03-developer-uploads-hello-world-2.md` | Signup → create marketplace → upload zip → served to Luna |
| 04 | `04-luna-adds-marketplace.md` | Luna Settings → Marketplaces: add URL, identity shows |
| 05 | `05-luna-installs-and-runs.md` | Marketplace pane lists hello-world; install; tool answers in chat |

## Results
Write run results to `dojo/results/NNNN-002-first-marketplace/` with `summary.md`
and a `screenshots/` folder, per the dojo convention.
