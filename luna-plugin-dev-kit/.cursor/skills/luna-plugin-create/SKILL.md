---
name: luna-plugin-create
description: Creates a new Luna plugin from scratch — scaffold from the template, write the manifest + tool(s) against luna_sdk, test locally, open-source it under github.com/huemorgan, and publish to a marketplace. Use when the user asks to build/create/scaffold/start a new Luna plugin.
---

# Create a Luna Plugin

Follow the full process in **`../../../docs/CREATING-A-PLUGIN.md`** (dev-kit root). Summary:

## Steps
1. **Scaffold** — copy the kit's `template/` to `plugins/<name>/`; rename the package dir
   (snake_case, e.g. `weather`). Plugin name is kebab-case.
2. **Manifest** — edit `luna-plugin.toml` (`name`, `version`, `entry`, `tags`, `readme`,
   `[requires]`, `[[tools]]`). Mirror `name`/`version`/`description` in the `PluginManifest`.
3. **Tool(s)** — in `on_load`, register each tool with `ctx.tool_registry.register(...)`;
   handlers are `async def` returning a JSON-serializable dict. Honest `policy` + `risk_level`.
4. **Test** — `pip install -e ".[dev]" && pytest`, then load into a real Luna and confirm the
   agent calls the tool. (Local plugins need no marketplace.)
5. **Open-source** — `gh repo create huemorgan/<name> --public --source=. --push`; tag
   `v<version>`. Link the repo in the manifest `readme`.
6. **Publish** — `python scripts/package_plugin.py plugins/<name>` then
   `scripts/publish_plugin.sh <name>-<version>.zip <slug>`. First-party → `official` via the
   repo-seeded path (see luna-plugin-update skill).
7. **Verify** — `curl -s https://marketplaces.com.ai/mp/<slug>/index.json` lists it; install
   in Luna and run the tool.

## Hard rules
- `luna_sdk` only — never `import luna.*`.
- One top-level package dir per zip; `entry` matches it.
- Keep `luna-plugin.toml` and `PluginManifest` in sync.
- Secrets via `ctx.vault`, never hard-coded; declare `depends_on=["plugin-vault"]`.
- Every plugin is also a public repo at `github.com/huemorgan/<plugin-name>`.

For the deeper model see the **luna-plugin-architecture** skill.
