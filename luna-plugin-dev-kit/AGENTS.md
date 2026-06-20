# AGENTS.md — Luna plugin development

You are working in the **Luna Plugin Dev Kit**. Use it to build, update, and publish Luna
plugins. Cursor users also get this as Agent Skills in `.cursor/skills/`.

## Read these (source of truth)
1. `docs/PLUGIN-ARCHITECTURE.md` — how Luna plugins work (start here).
2. `docs/SETUP-EXISTING-PLUGINS.md` — pull existing plugins, workspace setup.
3. `docs/CREATING-A-PLUGIN.md` — build a new plugin end to end.
4. `docs/UPDATING-A-PLUGIN.md` — change → version bump → publish.

## Pick the task
- **Set up / pull existing plugins** → run `python scripts/sync_plugins.py`, open
  `luna-plugins.code-workspace`. (See doc 2.)
- **Create a plugin** → scaffold from `template/`, follow doc 3.
- **Update a plugin** → bump the version in BOTH `luna-plugin.toml` and the `PluginManifest`,
  follow doc 4.

## Always-true rules
- Plugins import `luna_sdk` only — **never `import luna.*`**.
- Keep `luna-plugin.toml` and `PluginManifest` in sync (name, version, tools).
- One top-level package dir per plugin zip; `entry` matches that dir.
- Every tool declares an honest `policy` (`auto_approve`|`ask`|`prompt_always`) and
  `risk_level` (`low`|`medium`|`high`).
- Secrets come from `ctx.vault` (declare `depends_on=["plugin-vault"]`), never hard-coded.
- Published versions are immutable — every change is a new semver version.
- Every plugin is also a public repo at `github.com/huemorgan/<plugin-name>`.

## Endpoints
- Marketplace root (paste into Luna → Settings → Marketplaces): `https://marketplaces.com.ai/mp/official/`
- API base: `https://marketplaces.com.ai`
- This kit: `https://marketplaces.com.ai/dev-kit.zip`
