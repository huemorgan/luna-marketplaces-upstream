# 004 — Permanent plugin delete: dojo scenarios

Plan: `plan/004-permanent-plugin-delete/PLAN.md`

## S1 — Delete purges rows, history, and bytes

1. Start the service against a throwaway DB + artifacts dir.
2. Signup, create org + marketplace `dojo-mp`.
3. Upload `examples/hello_world_2` zip; download the artifact once (creates a
   `download` usage event on top of the `publish` one).
4. `DELETE /api/marketplaces/dojo-mp/plugins/hello-world-2` (the exact call the
   UI's "Delete plugin permanently" button makes).
5. Expect response counts: `versions_removed=1, artifacts_purged=1, events_purged=2`.
6. Verify: catalog detail 404s, plugin absent from `/mp/dojo-mp/index.json`,
   artifact zip gone from disk, `artifacts` row gone, zero `usage_events`
   rows for the plugin.
7. Verify other marketplaces' plugin of the same name (seeded `official`) is
   untouched.

## S2 — Shared artifact survives until last reference (pytest)

Same zip published to two marketplaces → same content hash. Deleting from the
first purges rows/history but keeps bytes (`artifacts_purged=0`); deleting from
the second garbage-collects the file. Then the same name@version republishes
successfully. Covered in `service/tests/test_permanent_delete.py`.

## S3 — UI wording

Danger-zone button reads "Delete plugin permanently"; confirm dialog and
caption state that all versions, download history and stored artifacts are
erased.
