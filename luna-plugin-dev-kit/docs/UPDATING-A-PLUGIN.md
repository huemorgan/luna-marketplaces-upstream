# Updating a Plugin (change → version bump → deploy)

> How to ship a change to an existing plugin. The golden rule: **published versions are
> immutable — every change is a new version.**

---

## The version-bump rule

A published `name@version` is frozen bytes. You cannot overwrite it (the service rejects a
re-publish of the same `name@version` with different bytes — **409**). To ship anything, you
**bump the version** and publish again. Luna then offers the new version as an update.

### Semver, briefly
- **patch** `0.1.0 → 0.1.1` — bug fix, no behavior change for callers.
- **minor** `0.1.1 → 0.2.0` — new tool / new optional arg / additive change.
- **major** `0.2.0 → 1.0.0` — removed/renamed a tool, changed required args, breaking.

When you remove or rename a tool, also update `[requires] tools = N` and the `[[tools]]` list.

### Bump in BOTH places (they must agree)
1. `luna-plugin.toml` → `version = "0.2.0"`
2. `__init__.py` → `PluginManifest(version="0.2.0", ...)`

A mismatch is the #1 cause of confusing installs. Keep them identical.

---

## Workflow

```
Task Progress:
- [ ] 1. Make the change
- [ ] 2. Bump version in toml + manifest
- [ ] 3. Test (unit + inside a real Luna)
- [ ] 4. Commit, tag, push the public repo
- [ ] 5. Publish the new version
- [ ] 6. Verify the new version is live + installs as an update
```

### 1–3. Change, bump, test
Edit the code, bump both versions, then run the local loop:
```bash
pytest
# and load into a real Luna to confirm agent behavior (see CREATING-A-PLUGIN.md §4)
```

### 4. Commit + tag the public repo
Each version gets a git tag in `github.com/huemorgan/<plugin-name>`:
```bash
git add -A && git commit -m "feat: <what changed> (v0.2.0)"
git tag v0.2.0 && git push && git push --tags
```

### 5. Publish — two paths

**Path A — runtime upload (your own / third-party marketplace).** Instant, no redeploy:
```bash
python scripts/package_plugin.py my-plugin            # -> my-plugin-0.2.0.zip
scripts/publish_plugin.sh my-plugin-0.2.0.zip my-mp   # your marketplace slug
```

**Path B — core / repo-seeded (first-party plugins in `official`).** Edit the source in the
`luna-marketplaces` service repo under `marketplace-src/<pkg>/`, bump the version, then deploy:
```bash
# in the luna-marketplaces repo
git add marketplace-src/my_plugin/ && git commit -m "feat: my-plugin v0.2.0" && git push
# then trigger a deploy (auto-deploy may be OFF — use Render dashboard → Manual Deploy)
```
On boot the seeder upserts the new version (same bytes → skipped; new version → added).

### 6. Verify
```bash
curl -s https://marketplaces.com.ai/mp/<slug>/index.json | python3 -m json.tool
```
The catalog should show the new `version` and a new `sha256`. In Luna's Marketplace pane the
plugin now offers the update; installing pulls the new artifact (hash-verified).

---

## Gotchas

- **Immutable versions.** Re-publishing the same `name@version` with different bytes → 409.
  Always bump.
- **Bump both files.** `toml` and `PluginManifest` must match.
- **Tool changes = manifest changes.** Update `[requires] tools` and `[[tools]]` when you
  add/remove tools.
- **One top-level dir in the zip.** `my-plugin.zip` → `my_plugin/…`, not loose files.
- **Tag every version** in the public repo so source and marketplace stay traceable.
- **`official` is owner-gated.** First-party updates go through Path B; you can't upload to
  `official` unless you own it.
