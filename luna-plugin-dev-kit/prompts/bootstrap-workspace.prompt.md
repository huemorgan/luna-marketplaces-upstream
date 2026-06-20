# Prompt: bootstrap a Luna plugin workspace

Paste this into a coding agent (Cursor, etc.) in an **empty new project folder** that contains
this dev kit. It will pull every existing plugin and set you up to build.

---

```
You are setting up my workspace for developing Luna plugins. This folder contains the
"luna-plugin-dev-kit" (docs/, template/, scripts/, luna-plugins.code-workspace).

Do the following, in order:

1. Read docs/PLUGIN-ARCHITECTURE.md, docs/SETUP-EXISTING-PLUGINS.md,
   docs/CREATING-A-PLUGIN.md, and docs/UPDATING-A-PLUGIN.md so you understand the Luna
   plugin model, the v0 marketplace protocol, and the version-bump/publish rules. These are
   your source of truth for everything below.

2. Run `python scripts/sync_plugins.py` to pull the source of every plugin currently
   published in the official marketplace (https://marketplaces.com.ai/mp/official/) into
   ./plugins/. If `gh` is available and I ask for editable clones, use
   `python scripts/sync_plugins.py --from-github` instead.

3. Confirm the multi-root workspace `luna-plugins.code-workspace` includes plugins/*,
   template/, and docs/ as roots so I can see everything in one window.

4. Give me a short summary: which plugins were pulled (name + version + one-line purpose from
   each luna-plugin.toml), and which ones are "leaf" (tools only) vs "connector" (settings/
   routes/deps) — so I know which to copy patterns from.

Then STOP and ask me what I want to build or change. When I tell you:
- To build a NEW plugin: follow docs/CREATING-A-PLUGIN.md (scaffold from template/, snake_case
  package dir + kebab-case name, honest policy/risk per tool, luna_sdk only — NO import luna.*,
  unit test + local Luna test, then a public repo at github.com/huemorgan/<name>, then publish).
- To UPDATE a plugin: follow docs/UPDATING-A-PLUGIN.md (bump version in BOTH luna-plugin.toml
  and the PluginManifest, never overwrite a published version, tag the repo, publish, verify).

Rules you must always follow:
- Plugins import `luna_sdk` only. Never `import luna.*`.
- Keep luna-plugin.toml and the PluginManifest in sync (name, version, tools).
- One top-level package dir per plugin zip.
- Published versions are immutable — every change is a new semver version.
- Every plugin is also a public repo under github.com/huemorgan/<plugin-name>.
```
