---
name: luna-plugin-update
description: Updates an existing Luna plugin — make the change, bump the semver version in BOTH luna-plugin.toml and the PluginManifest, test, tag the public repo, and re-publish (runtime upload or repo-seeded core). Use when the user asks to change, modify, fix, version-bump, release, or re-deploy an existing Luna plugin.
---

# Update a Luna Plugin

Follow **`../../../docs/UPDATING-A-PLUGIN.md`** (dev-kit root). Summary:

## The golden rule
Published `name@version` bytes are **immutable**. Re-publishing the same version with
different bytes is rejected (409). **Every change = a new semver version.**

## Steps
1. **Change** the code.
2. **Bump the version in BOTH places** (they must match):
   - `luna-plugin.toml` → `version`
   - `__init__.py` → `PluginManifest(version=...)`
   Choose: patch (fix), minor (additive/new tool), major (breaking/removed/renamed tool).
   If tools changed, update `[requires] tools = N` and the `[[tools]]` list too.
3. **Test** — `pytest`, then load into a real Luna.
4. **Tag the public repo** — `git commit`, `git tag v<version>`, `git push --tags` on
   `github.com/huemorgan/<name>`.
5. **Publish**:
   - **Runtime upload** (your/third-party marketplace): `package_plugin.py` →
     `publish_plugin.sh <zip> <slug>`. Instant.
   - **Core / repo-seeded** (`official`): edit `marketplace-src/<pkg>/` in the
     `luna-marketplaces` service repo, bump version, push, then trigger a Render deploy
     (auto-deploy may be OFF).
6. **Verify** — `curl -s https://marketplaces.com.ai/mp/<slug>/index.json` shows the new
   `version` + new `sha256`; Luna offers it as an update.

## Gotchas
- Bump both files; mismatches cause confusing installs.
- One top-level dir per zip.
- `official` is owner-gated → first-party updates go through the repo-seeded path.
