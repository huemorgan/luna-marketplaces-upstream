# 003 — Bundles: curated groups of plugins with their own marketing + version

> A bundle is a marketing-enabled group of **existing** plugins in a marketplace.
> It has its own identity (title, image, description/readme, tags) and its own
> version. Each bundle version **pins exact plugin versions**. A plugin releasing
> a new version does NOT change any bundle — an editor must publish a new bundle
> version with updated pins.

## Why

Plugins are atomic capabilities. Some capabilities only make sense together
("Mission Oriented" = wiki + scheduler + curiosity). A bundle lets a marketplace
curate and market that combination as one installable story, while keeping the
member plugins independently versioned and independently upgradable.

## Core rules

1. **A bundle references existing plugins in the same marketplace.** No new
   artifacts — bundle install reuses the member plugins' existing artifacts.
2. **Pins are explicit.** `BundleVersion.items = [{plugin_name, version}, ...]`.
   Publish-time validation: every pinned (plugin, version) must exist.
3. **Bundle versions are immutable.** Same bundle version cannot change its pin
   set (mirrors plugin artifact immutability). To change pins → new bundle version.
4. **Plugin upgrades don't propagate.** `plugin-wiki 0.4.0` shipping does not
   touch a bundle pinning `plugin-wiki 0.3.2`. Bundle editors act deliberately.
5. **Marketing surface parity with plugins:** name, title-ish display name,
   description, readme, tags, icon/image URL.

## Data model (service/app/models/db.py)

New tables only — no changes to existing tables (safe with `create_all`):

- `bundles`: `id`, `marketplace_id` FK, `name` (slug-like, unique per
  marketplace), `title` (display), `description`, `readme`, `tags` JSON,
  `icon_url`, `latest_version`, `download_count`, `created_at`, `updated_at`.
- `bundle_versions`: `id`, `bundle_id` FK, `version`, `items` JSON
  (`[{"plugin_name": str, "version": str}]`), `published_at`, `yanked`.

## API

Management (auth = same `_get_marketplace_for_publisher` gate as plugins):
- `POST   /api/marketplaces/{slug}/bundles` — create bundle + first version.
- `PATCH  /api/marketplaces/{slug}/bundles/{name}` — edit marketing metadata.
- `POST   /api/marketplaces/{slug}/bundles/{name}/versions` — publish new
  version with a new pin set (immutability enforced).
- `DELETE /api/marketplaces/{slug}/bundles/{name}` — remove bundle + versions.
- `POST   /api/marketplaces/{slug}/bundles/{name}/versions/{version}/yank`

Browse (public):
- `GET /api/catalog/{slug}/bundles` — list bundles with resolved latest pins.
- `GET /api/catalog/{slug}/bundles/{name}` — bundle detail + version history.

## Registry protocol (what Luna consumes)

`GET /mp/{slug}/index.json` gains an additive top-level `bundles` array
(protocol_version stays "0"; old clients ignore unknown keys):

```json
{
  "marketplace": {...},
  "protocol_version": "0",
  "plugins": [...],
  "bundles": [
    {
      "name": "mission-oriented",
      "version": "1.0.0",
      "title": "Mission Oriented",
      "description": "...",
      "icon_url": "...",
      "items": [
        {"name": "plugin-wiki", "version": "0.3.2",
         "artifact": "plugins/plugin-wiki/0.3.2/artifact.zip", "sha256": "..."}
      ]
    }
  ]
}
```

Items are **fully resolved** (artifact path + sha256 of the pinned version), so
Luna installs bundle members through the exact same integrity gate as single
plugins — no second resolution step. Pinned versions are served even if later
yanked (yank hides from the `plugins[]` latest-pick, pins are explicit).

## Dashboard UI (templates/app.html)

- Marketplace view gets a **Bundles** tab next to Plugins: list of bundles
  (icon, title, version, item count), "New Bundle" form (name, title,
  description, image URL, tags + plugin picker with per-plugin version select).
- Bundle drawer (mirrors plugin drawer): marketing metadata edit, pinned items
  list, version history with yank, "publish new version" (re-pick pins,
  defaulting to current pins), delete.
- Public catalog (`templates/catalog.html`): bundles strip above the plugin
  grid with marketing display.

## Tests (service/tests/test_bundles.py)

1. Create bundle → appears in `/api/catalog/{slug}/bundles` and in
   `/mp/{slug}/index.json` `bundles[]` with resolved sha256s.
2. Pin validation: creating with a nonexistent plugin/version → 400.
3. Immutability: republishing same bundle version with different pins → 409.
4. Plugin publishes newer version → bundle pins unchanged (explicit test).
5. Yank bundle version → drops out of index; un-yank restores.
6. Permission gates: non-editor 403.

## Out of scope

- Bundle-level pricing/licensing (bundles inherit member plugin licenses).
- Cross-marketplace bundles.
- Auto-suggested pin upgrades (future: "pins behind latest" indicator exists
  in API data; a one-click "update pins" UI can come later).

## Rollout

1. Implement models + API + registry + UI + tests locally (SQLite).
2. Deploy to Render (new tables auto-create; Postgres `create_all` is additive).
3. Create the **Mission Oriented** bundle in production: plugin-wiki,
   plugin-scheduler, plugin-curiosity pinned at current versions, with
   marketing copy + image.
