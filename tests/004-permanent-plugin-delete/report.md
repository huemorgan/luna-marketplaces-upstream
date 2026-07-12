# 004 — Permanent plugin delete: test report

Date: 2026-07-09

## Results

| Scenario | Result |
|---|---|
| S1 live-server purge (rows + history + bytes) | PASS |
| S2 shared-artifact refcount + republish (pytest) | PASS |
| S3 UI wording | PASS (code-inspected; see caveat) |

## S1 — live server run (uvicorn, throwaway sqlite + artifacts dir)

- Published `hello-world-2@0.1.0` to `dojo-mp`, downloaded once.
- `DELETE /api/marketplaces/dojo-mp/plugins/hello-world-2` returned:
  `{"status":"deleted","plugin":"dojo-mp/hello-world-2","versions_removed":1,"artifacts_purged":1,"events_purged":2}`
- After delete: catalog detail `404`; plugin absent from
  `/mp/dojo-mp/index.json`; artifact zip removed from disk; `artifacts` row
  gone; `usage_events` rows for the plugin = 0.
- Same-named seeded plugin in the `official` marketplace untouched (scoping
  correct).

## S2 — pytest

`service/tests/test_permanent_delete.py` — same zip in two marketplaces:
first delete keeps the shared bytes (`artifacts_purged=0`), second delete
removes them (`artifacts_purged=1`, file gone), then `name@0.1.0` republishes
cleanly. Full suite: **16 passed**.

## Caveat

No Playwright MCP was connected in this session, so the browser click-through
(S3) was not visually executed; the UI delete path was exercised via the exact
HTTP call `deletePlugin()` makes, and the wording changes were verified in
`service/templates/app.html`. Run a real dojo browser pass when the MCP is
available.
