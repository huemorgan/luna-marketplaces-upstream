# 004 — Permanent plugin delete (purge history + artifacts)

## Context

`DELETE /api/marketplaces/{slug}/plugins/{name}` already exists
(`service/app/routers/plugins.py:387`) and is exposed in the web UI's
"Danger zone" drawer. But it only deletes the `Plugin` and `PluginVersion`
rows. Left behind after a delete:

1. **Artifact bytes on disk** (`{ARTIFACTS_DIR}/{sha[:2]}/{sha}.zip`) and their
   `Artifact` rows — orphaned forever (`storage.py` has no delete).
2. **`UsageEvent` history** (`publish`/`download` rows keyed by
   `plugin_name`) — the plugin's history survives deletion.

The registry index (`/mp/{slug}/index.json`) is query-based, so deleted
plugins already disappear immediately; bundles pinning a deleted plugin are
already dropped from the index (`registry.py:122`). No gap there.

Goal per user request: deleting a plugin should be **permanent** — no
leftover history or bytes.

## Goals

- Make plugin delete a full purge, in the same endpoint:
  - delete `Plugin` + all `PluginVersion` rows (as today);
  - delete the plugin's `UsageEvent` rows (`plugin_name == "{namespace}/{name}"`,
    scoped to the marketplace);
  - garbage-collect artifacts: for each removed `artifact_hash`, if **no other**
    `PluginVersion` row (any marketplace) still references it, delete the
    `Artifact` row and the `.zip` on disk.
- Add `storage.delete(sha256)` (idempotent, missing file is a no-op).
- Response reports what was purged:
  `{status, plugin, versions_removed, artifacts_purged, events_purged}`.
- Update UI danger-zone copy + confirm dialog to say deletion is permanent and
  erases history.
- Tests in `tests/004-permanent-plugin-delete/`.

## Non-Goals

- Version-level permanent delete (yank already covers hiding a version).
- Soft delete / tombstones / undo.
- Name or version reservation after delete (see Risks).
- `luna-mp` CLI changes (it's the offline build/verify tool, not a service client).
- Cascading bundle edits (index already drops bundles with dangling pins;
  bundle rows stay editable by the owner).

## Approach

1. `service/app/storage.py`: add `delete(sha256)` — unlink the zip if present,
   ignore missing.
2. `service/app/routers/plugins.py` — `delete_plugin()`:
   - collect `artifact_hash`es of the plugin's versions before deleting rows;
   - delete versions + plugin (as today);
   - `flush` so refcount queries see the deletions, then for each hash with no
     remaining `PluginVersion` reference: delete `Artifact` row + `storage.delete()`;
   - delete `UsageEvent` rows for this marketplace whose `plugin_name` matches
     `{namespace}/{name}`;
   - commit once; return purge counts.
3. `service/templates/app.html`: confirm text →
   `Permanently delete "<name>"? All versions, download history and stored
   artifacts are erased. This cannot be undone.`; danger-zone caption updated
   to match.

## Data/API contract

`DELETE /api/marketplaces/{mp_slug}/plugins/{plugin_name}` (auth unchanged:
org owner/publisher or global editor) →

```json
{
  "status": "deleted",
  "plugin": "<slug>/<name>",
  "versions_removed": 3,
  "artifacts_purged": 3,
  "events_purged": 17
}
```

No schema/migration changes. No new routes.

## Risks

- **Immutability rule loophole**: once versions are purged, the same
  `name@version` can be republished with different bytes. Accepted — that is
  what "permanent" means; the 409 immutability check only guards live rows.
- **Shared artifacts**: content-addressed zips may back other plugins'
  versions. Mitigated by the refcount check before unlink.
- **Prod data loss is real**: this runs against the live Render service once
  deployed. The UI confirm dialog is the only guard; auth already restricts to
  owners/publishers.

## Acceptance criteria

- Deleting a plugin removes its rows, its usage events, and its artifact zips
  from disk when unreferenced; response reports the counts.
- An artifact shared with another plugin's version survives on disk and in the
  `artifacts` table.
- Catalog, `/mp/{slug}/index.json`, and version routes 404/omit the plugin
  immediately after delete.
- UI delete flow still works end-to-end with the new wording.

## Verification

- `service/tests`: pytest covering purge counts, shared-artifact survival,
  usage-event removal, and republish-after-delete succeeding.
- Dojo run (`tests/004-permanent-plugin-delete/`): publish a throwaway plugin
  locally, delete it via the UI, verify drawer closes, catalog refreshes,
  artifact file gone from `service/data/artifacts`, report in `report.md`.
