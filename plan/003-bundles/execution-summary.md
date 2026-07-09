# 003 Bundles — Execution Summary

Executed Jul 8–9 2026. Everything in PLAN.md shipped and is live in production.

## What was built (service)

| Piece | Where |
|---|---|
| `Bundle` + `BundleVersion` tables (pins stored as JSON items) | `service/app/models/db.py` |
| Bundle schemas (create/update/version/yank, resolved-item responses) | `service/app/models/schemas.py` |
| Management + browse API (create, patch, publish version, delete, yank, list, detail, version history) | `service/app/routers/bundles.py` (new) |
| Resolved `bundles[]` in the Luna registry index — each item carries the pinned version's artifact path + sha256 | `service/app/routers/registry.py` |
| Dashboard: Bundles tab, create form with pinned-version plugin picker, bundle drawer (edit marketing, publish new version, yank, delete) | `service/templates/app.html` |
| Public catalog: bundle cards strip above the plugin grid | `service/templates/catalog.html` |
| Tests — 6 new (lifecycle, pin validation, pin-doesn't-move, immutability, yank, permissions/delete) | `service/tests/test_bundles.py` |

Test result: **15/15 passed** (full service suite, 6 bundle tests included).

## Core rules as implemented

- Pins validated at publish: every (plugin, version) must exist in the marketplace → 400 otherwise.
- Bundle versions immutable: republishing an existing version → 409.
- A plugin releasing a new version does NOT move any bundle pin (explicit test).
- Yanked bundle versions drop out of the index; pins are served even if the
  pinned plugin version is later yanked from `plugins[]` latest-pick.
- A pin pointing at a deleted plugin/version drops the bundle from the Luna
  index entirely (uninstallable bundles are never advertised).
- Auth: same editor gate as plugins (`_get_marketplace_for_publisher`,
  including global editors for `official`).

## Deviations from plan

- Latest-version pick uses the `latest_version` pointer with newest-non-yanked
  fallback (published_at is second-granular; the pointer breaks ties).
- Bundles router registered before the plugins router so
  `/api/catalog/{slug}/bundles` wins over `/api/catalog/{slug}/{plugin_name}`.

## Deployment + production verification

- Deployed to Render (`srv-d8m7nct8nd3s73dofrm0`), deploy `dep-d97du08k1i2s73dg56f0` → live.
  New tables auto-created via `create_all` (additive, no migration needed).
- **Mission Oriented** bundle created in the `official` catalog:
  - v1.0.0 pinning `plugin-wiki@0.3.2`, `plugin-scheduler@0.2.2`, `plugin-curiosity@0.4.4`
  - All three artifact sha256s re-verified against served bytes — OK.
  - Visible on https://marketplaces.com.ai/browse/official (bundle card) and in
    the dashboard Bundles tab + drawer (screenshot-verified in a real browser).
- Luna's real `install_bundle()` code ran against production and installed all
  three members through the hash gate (loader stubbed): `ok: True`, 3/3.

## Luna-side counterpart

See `luna/plans/021-marketplace-bundles/` (PLAN.md + execution-summary.md):
core `install_bundle()`, plugin-marketplace 0.2.0 with bundle cards +
`/install-bundle` route, 5 unit tests green.
