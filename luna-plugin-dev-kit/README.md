# Luna Plugin Dev Kit

Everything you (and your coding agent) need to build, update, and publish **Luna plugins** —
and to teach the agent the rules so it does it correctly.

Download: **`https://marketplaces.com.ai/dev-kit.zip`** · Marketplace:
**`https://marketplaces.com.ai/mp/official/`**

---

## Quick start

```bash
# 1) Pull every existing plugin's source into ./plugins/
python scripts/sync_plugins.py

# 2) Open the multi-root workspace (docs + template + every plugin in one window)
cursor luna-plugins.code-workspace

# 3) Build a new plugin
cp -r template plugins/my-plugin    # then follow docs/CREATING-A-PLUGIN.md
```

Or paste **`prompts/bootstrap-workspace.prompt.md`** into your agent and let it do steps 1–2
and brief you on what's there.

---

## What's inside

```
luna-plugin-dev-kit/
  README.md                       ← this file
  AGENTS.md                       ← entry point for any coding agent
  luna-plugins.code-workspace     ← multi-root workspace (open this in Cursor)
  docs/
    PLUGIN-ARCHITECTURE.md        ← how Luna plugins work (read first)
    SETUP-EXISTING-PLUGINS.md     ← pull all existing plugins, workspace setup
    CREATING-A-PLUGIN.md          ← build a new plugin, end to end
    UPDATING-A-PLUGIN.md          ← change → version bump → deploy
  prompts/
    bootstrap-workspace.prompt.md ← paste into a fresh agent project
  template/                       ← scaffold for a new plugin (copy this)
  scripts/
    sync_plugins.py               ← pull existing plugins from the marketplace
    package_plugin.py             ← zip a plugin (single top-level dir)
    publish_plugin.sh             ← auth + upload to a marketplace
  .cursor/skills/                 ← the same knowledge as Cursor Agent Skills
    luna-plugin-architecture/
    luna-plugins-setup/
    luna-plugin-create/
    luna-plugin-update/
  plugins/                        ← populated by sync_plugins.py
```

## Make your agent "know" this

This kit ships **Cursor Agent Skills** in `.cursor/skills/`. If you unzip the kit into (or
beside) your project so that `.cursor/skills/` is at your workspace root, Cursor will surface
`luna-plugin-architecture`, `luna-plugins-setup`, `luna-plugin-create`, and
`luna-plugin-update` automatically. For other agents, point them at `AGENTS.md`.

## The five rules (that the whole kit enforces)

1. Plugins import **`luna_sdk` only** — never `import luna.*`.
2. `luna-plugin.toml` and the `PluginManifest` stay in sync (name, version, tools).
3. One top-level package dir per plugin zip.
4. Published versions are **immutable** — every change is a new semver version.
5. Every plugin is also a public repo at **`github.com/huemorgan/<plugin-name>`**.
