# 002 — First Real Marketplace: core-in-repo + service uploads + dev plugin pages

**Status:** PLAN ONLY — do not implement until approved.
**Thoroughness:** medium.
**Host:** Render (decided) — `https://luna-marketplaces.onrender.com`.
**Maps to:** ROADMAP 002 (`luna-e2e-proof`) + pulls forward parts of 003
(`service-mvp` publishing) and 004 (`catalog-and-curation` plugin pages).

---

## Context

Two sources of plugins, one marketplace:

1. **Core plugins live in our repo** (`marketplace-src/`), authored by us,
   seeded into the official marketplace on deploy. hello-world is the first.
2. **Everyone else adds plugins through the service at runtime** — zip upload
   or API, no repo commit, no redeploy. A developer uploads, the plugin is
   immediately served and gets its own public page with versions + downloads.

Luna consumes the result by pasting **one URL** into Settings → Marketplaces.

### What already exists (service)
- Models: `Marketplace`, `Plugin`, `PluginVersion` (with `manifest_data`,
  `artifact_hash`), `UsageEvent`, `Plugin.download_count`.
- `POST /api/marketplaces/{slug}/publish` (multipart: manifest JSON + zip).
- `GET /api/catalog/{slug}`, `/api/catalog/{slug}/{plugin}`, `/versions`.
- Browse + plugin-detail templates; management SPA with an upload stub.

### What's missing (the gaps this plan closes)
- **G1 — Luna can't consume it.** No `/index.json`,
  `/.well-known/luna-marketplace.json`, or artifact-download endpoint in
  Luna's v0 shape. (Reference shape: `luna/fixtures/build_marketplace.py`,
  consumer: `luna/luna/plugins/install.py`.)
- **G2 — Uploads don't survive deploys.** Artifacts are written to the
  container's local disk (`data/artifacts/...`), which is **ephemeral on
  Render**. Must persist on a **mounted Render persistent disk**.
- **G3 — No core-from-repo seeding.** hello-world isn't in our repo or DB.
- **G4 — Upload UX is split** (manifest as a separate JSON field). A dev
  should upload just a zip; the service reads the manifest from inside it.
- **G5 — Plugin page is thin.** Needs README, version history, downloads,
  permissions, publisher — the developer's product surface.

## Luna's v0 contract (what we must serve, per marketplace slug)

| Path (under the marketplace root URL) | Shape |
|---|---|
| `/.well-known/luna-marketplace.json` | `{id, name, protocol_version}` |
| `/index.json` | `{marketplace:{id,name}, protocol_version, plugins:[{name, version, description, sdk_version, requires, artifact, sha256}]}` |
| `/plugins/{name}/{version}/artifact.zip` | the zip (one top-level package dir) |

Hard rule: `sha256` == hash of the artifact bytes, or Luna refuses to load.
Marketplace root URL we hand Luna: **`https://luna-marketplaces.onrender.com/mp/official/`**.

## Goals

1. Plugin **source convention** (folder = one package dir + `luna-plugin.toml`),
   shared by core-in-repo and uploads.
2. **hello-world in our repo** under `marketplace-src/`, seeded into the
   official marketplace on deploy (idempotent, content-addressed).
3. Service **serves Luna's v0 protocol dynamically from the DB** at
   `/mp/{slug}/...`, with correct `sha256` and a working artifact download.
4. **Durable artifacts on a mounted Render persistent disk** (survive
   redeploys/restarts).
5. **Upload a plugin via the service** (zip; manifest read from the zip) →
   live in the index with no redeploy. Demo: **hello-world-2**.
6. **Full developer plugin page**: description, README, version history,
   permissions, publisher, **download count**; dashboard shows the dev's
   plugins + stats.
7. **E2E in Luna**: paste the URL → install **hello-world** (core) AND
   **hello-world-2** (uploaded) → call their tools → screenshots.

## Non-Goals

- Signing / key-pinning / permissions-diff (P5 hardening; v0 = sha256 only).
- Object storage / CDN (a mounted disk is enough for v0; revisit if we need
  horizontal scaling across instances).
- Dependency isolation (leaf plugins, no deps).
- Private-marketplace token auth on the served protocol (official is public).
- Pricing/quota enforcement.

## Architecture impact

- `ADD: dynamic v0 protocol serving from DB` → `service`; document the
  client-facing shape in `spec/02-index.md`.
- `ADD: artifacts persisted on a mounted Render disk` → content-addressed
  files on the disk + `artifacts` metadata table; supersedes the ephemeral
  container `data/artifacts/` path in `routers/plugins.py`. Adds a `disk:`
  block to `render.yaml`.
- `ADD: core-plugin seeding from marketplace-src/` → `service` startup seeder.
- `ADD: manifest-from-zip ingestion` → `routers/plugins.py` publish path.
- `ADD: developer plugin page + download metering on fetch` → templates +
  `routers/plugins.py`.
- Decision (below) supersedes 001-plan's "static files / build at Docker time":
  v0 is **DB-backed dynamic serving** so runtime uploads appear without redeploy.

## Key decisions (resolve at execution start — current recommendations)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Artifact storage | **Mounted Render persistent disk** (decided by owner). Content-addressed files at `{DISK}/artifacts/{sha256[:2]}/{sha256}.zip`; an `artifacts(sha256 PK, size, created_at)` metadata row; `PluginVersion` references `sha256`. Add `disk:` to `render.yaml` (mount `/data`, ~1–5 GB), set `ARTIFACTS_DIR=/data/artifacts`. |
| D2 | Manifest source on upload | **Read `luna-plugin.toml` (fallback `manifest.json`) from inside the zip.** Single source of truth, matches authoring. Optional form fields override README/tags only. |
| D3 | Core ingestion | **Seed `marketplace-src/*` into the official marketplace DB on startup**, idempotent by sha256. Same DB path as uploads → uniform serving. |
| D4 | Serving mode | **Dynamic from DB** at `/mp/{slug}/...` (not static files), so uploads are live immediately. |
| D5 | Official marketplace identity | Fixed seeded `Marketplace.id` + slug `official` so Luna's pinned id is stable across deploys. |

## Approach (phased — each phase leaves the service deployable)

### P0 — Source convention + repo core plugin
- `marketplace-src/hello-world/` = `hello_world/__init__.py` (imports only
  `luna_sdk`) + `luna-plugin.toml`. Copied from `luna/fixtures/hello-world/`
  (we own the source now).
- Shared **deterministic packager** (sorted paths, skip `__pycache__`, fixed
  mtime) producing `(zip_bytes, sha256)` — reused by the seeder and by upload
  so hashes are stable. Land it in `service/app/packaging.py` (and optionally
  mirror in `luna-mp` later).

### P1 — Durable storage + dynamic v0 protocol serving (closes G1, G2)
- D1: add a `disk:` block to `render.yaml` (mount at `/data`); set
  `ARTIFACTS_DIR=/data/artifacts`. Add an `artifacts` metadata table; a small
  storage helper writes/reads content-addressed files on the disk
  (`{ARTIFACTS_DIR}/{sha256[:2]}/{sha256}.zip`). Migrate `publish` to use it;
  remove the ephemeral container-local writes.
- Add protocol routes (new `routers/registry.py`), per marketplace slug:
  - `GET /mp/{slug}/.well-known/luna-marketplace.json`
  - `GET /mp/{slug}/index.json` (built from DB: latest non-yanked version per
    plugin; fields mapped from `manifest_data`/`PluginVersion`)
  - `GET /mp/{slug}/plugins/{name}/{version}/artifact.zip` (streams bytes from
    `artifacts`; increments `download_count`; records `UsageEvent(download)`)
- Verify `sha256` round-trips (served bytes hash == index `sha256`).

### P2 — Seed core plugins (closes G3)
- Startup seeder: for each `marketplace-src/*`, package deterministically,
  upsert `Plugin` + `PluginVersion` + `artifacts` into the `official`
  marketplace (D3, D5). Idempotent: skip if same sha256 already present.
- Result: `/mp/official/index.json` lists hello-world right after deploy.

### P3 — Upload flow end-to-end (closes G4)
- Change/extend `publish` (and the SPA upload form) so a dev uploads **just a
  zip**; service reads the manifest from inside (D2), validates one top-level
  package dir, stores version + bytes, updates the index live.
- Demo path: duplicate hello-world → `hello-world-2` (rename package + tool +
  manifest), upload via the SPA, confirm it appears in `/mp/official/index.json`
  without a redeploy.

### P4 — Developer plugin page + stats (closes G5)
- Extend the public plugin page (`templates/plugin_detail.html`): description,
  README (markdown), **version history**, permissions summary (tools/policies,
  egress, vault, UI), publisher/org, **download count**, install snippet
  (the marketplace URL + plugin name for Luna).
- Dashboard (SPA): the developer's plugins with per-plugin downloads +
  versions + last published.
- Downloads come from P1's metering (artifact fetch → `UsageEvent` +
  `download_count`).

### P5 — Verify E2E in Luna (dojo)
- `curl`/script: pull `/mp/official/index.json`, recompute each artifact's
  sha256, assert match (hello-world + hello-world-2).
- Real-browser dojo against local Luna (submodule `8.5-pluginsdk`): Settings →
  Marketplaces → paste `https://luna-marketplaces.onrender.com/mp/official/` →
  Add → browse → install **hello-world** → install **hello-world-2** → ask the
  agent to call each tool → screenshot greetings.
- Confirm a download bump shows on each plugin's page after install.
- Evidence → `tests/002-first-marketplace/evidence/`.

## Data / API contract

- `artifacts(sha256 text pk, size int, created_at int)` (metadata only; bytes
  live on the mounted disk at `{ARTIFACTS_DIR}/{sha256[:2]}/{sha256}.zip`).
- `index.json` per-plugin entry maps: `name`←Plugin.name, `version`←latest
  non-yanked PluginVersion.version, `description`←Plugin.description,
  `sdk_version`←manifest `sdk_version`/`compat.sdk`, `requires`←
  `capabilities_required`, `artifact`←`plugins/{name}/{version}/artifact.zip`,
  `sha256`←PluginVersion.artifact_hash (== artifacts.sha256).
- Upload zip MUST contain exactly one top-level dir with `__init__.py` and a
  `luna-plugin.toml` (at zip root or beside the package — define one, document
  it).

## Risks

| Risk | Mitigation |
|---|---|
| Render FS ephemeral loses uploads (G2) | D1 — store on the mounted persistent disk (`/data`), not container-local FS. |
| Zip nondeterminism → sha256 drift | Single deterministic packager (P0); hash the exact stored bytes. |
| Index served shape ≠ Luna's reader | Cross-check `luna/luna/plugins/install.py` before shipping P1; assert in a test. |
| Mounted disk ties service to one instance | Acceptable for v0 (single instance). Object storage is the scale-out path, noted as future. |
| Manifest-in-zip vs current JSON-field API | Accept both during transition; SPA switches to zip-only. |

## Acceptance criteria

- [ ] `marketplace-src/hello-world/` imports only `luna_sdk`; deterministic
      packager yields a stable sha256.
- [ ] Artifacts persist on the mounted disk; survive a redeploy/restart.
- [ ] `/mp/official/index.json` + identity + artifact serve in Luna's v0 shape;
      served-bytes sha256 == index sha256 (tested).
- [ ] hello-world auto-seeded from repo on deploy.
- [ ] A zip upload via the service adds hello-world-2 live (no redeploy).
- [ ] Plugin page shows README, versions, permissions, publisher, downloads.
- [ ] Dojo: real Luna installs both plugins from the URL and runs their tools.
- [ ] `tests/002-first-marketplace/report.md` with real results + screenshots.

## Verification

```bash
# index + hash check (both plugins)
python - <<'PY'
import hashlib, json, urllib.request
base="https://luna-marketplaces.onrender.com/mp/official/"
idx=json.load(urllib.request.urlopen(base+"index.json"))
for p in idx["plugins"]:
    b=urllib.request.urlopen(base+p["artifact"]).read()
    assert hashlib.sha256(b).hexdigest()==p["sha256"], p["name"]
print("ok", [(p["name"],p["version"]) for p in idx["plugins"]])
PY
# service unit/integration tests
cd service && pytest
# e2e: dojo against local Luna (real browser per .cursor rules)
```
