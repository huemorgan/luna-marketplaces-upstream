---
name: luna-plugin-architecture
description: Explains how Luna plugins work — the LunaPlugin lifecycle, manifest-as-data, tools/skills/routes/UI/settings, tool policy + risk levels, packaging + the sha256 trust gate, and the v0 marketplace protocol. Use when reading, explaining, designing, or reviewing any Luna plugin, or when the user mentions luna_sdk, luna-plugin.toml, PluginManifest, ToolDef, or a Luna marketplace.
---

# Luna Plugin Architecture

When working on anything Luna-plugin-related, ground yourself in the architecture before
editing code.

## Read first
The authoritative reference is **`../../../docs/PLUGIN-ARCHITECTURE.md`** (relative to this
skill, at the dev-kit root). Read it before designing or reviewing a plugin.

## The essentials (so you can act without re-reading every time)
- A plugin is a Python package built against **`luna_sdk` only** — never `import luna.*`.
- Two files define it: `luna-plugin.toml` (data manifest, read without importing) and
  `<package>/__init__.py` (a `LunaPlugin` subclass). Keep `name`/`version`/tools in sync.
- Capabilities are registered in `async def on_load(self, ctx)`: tools
  (`ctx.tool_registry.register`), skills (`ctx.skill_registry.register`), routes
  (`routes_module`), settings UI (`settings_tabs` + `interfaces`), secrets (`ctx.vault`).
- Every tool declares `policy` (`auto_approve` | `ask` | `prompt_always`) and `risk_level`
  (`low` | `medium` | `high`). Reads = auto/low; writes = ask/medium; deletes/secrets =
  prompt_always/high.
- Published artifacts are content-addressed by **sha256**; the catalog hash must equal the
  artifact bytes or Luna refuses to load. This is the trust gate.
- A marketplace = three URLs under a root: `.well-known/luna-marketplace.json`, `index.json`,
  `plugins/{name}/{version}/artifact.zip`. Official root:
  `https://marketplaces.com.ai/mp/official/`.
- Versions are immutable semver — change ⇒ new version.

## Reference plugins to copy patterns from
- `hello-world` — minimal leaf (one tool).
- `plugin-files` — tools + backend routes + standalone UI.
- `plugin-render` — connector: many tools grouped into skills, settings iframe, vault dep.
