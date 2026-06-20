# Creating a New Plugin

> A repeatable process to go from nothing to a published, installable Luna plugin.
> Assumes you've read `PLUGIN-ARCHITECTURE.md`.

---

## The process at a glance

```
Task Progress:
- [ ] 1. Scaffold from the template
- [ ] 2. Name + manifest
- [ ] 3. Write the tool(s)
- [ ] 4. Test locally (unit, then inside a real Luna)
- [ ] 5. Open-source it (github.com/huemorgan/<name>)
- [ ] 6. Publish to the marketplace
- [ ] 7. Verify it installs in Luna
```

The marketplace is only step 6 — most of the work is the local loop (steps 1–4).

---

## 1. Scaffold from the template

Copy the kit's `template/` into a new plugin folder and rename the package dir:

```bash
cp -r template plugins/my-plugin
cd plugins/my-plugin
git mv my_plugin "$(echo my_plugin)"   # rename my_plugin/ to your package name, e.g. weather/
```

A plugin package dir name is **snake_case** (`weather`); the plugin **name** is **kebab-case**
(`weather`). Pick a clear, unique name.

## 2. Name + manifest

Edit `luna-plugin.toml` — this is read without importing your code:

```toml
name = "weather"               # kebab-case, unique in the marketplace
version = "0.1.0"              # semver; immutable once published
description = "Current weather + forecasts for any city."
entry = "weather"             # the package dir with __init__.py
sdk_version = "0"
license = "MIT"
tags = ["weather", "connector"]
readme = """
# weather
What it does, the tools it adds, any config/env it needs.
Source: https://github.com/huemorgan/weather
"""

[requires]
tools = 1                      # capability counts Luna reconciles against
# depends_on = ["plugin-vault"]  # uncomment if you need secrets

[[tools]]
name = "get_weather"
description = "Get current weather for a city."
policy = "auto_approve"
risk_level = "low"
```

Keep the `PluginManifest` in `__init__.py` in sync (`name`, `version`, `description`).

## 3. Write the tool(s)

In `__init__.py`, register each tool in `on_load`. A tool handler is an `async def` returning
a JSON-serializable `dict`:

```python
from luna_sdk import LunaPlugin, PluginContext, PluginManifest, ToolDef

class WeatherPlugin(LunaPlugin):
    manifest = PluginManifest(name="weather", version="0.1.0",
                              description="Current weather + forecasts for any city.")

    async def on_load(self, ctx: PluginContext) -> None:
        async def _get_weather(city: str) -> dict:
            # ... call an API, do work ...
            return {"city": city, "temp_c": 21, "conditions": "clear"}

        ctx.tool_registry.register(self.manifest.name, ToolDef(
            name="get_weather",
            description="Get current weather for a city.",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
            },
            policy="auto_approve", risk_level="low",
        ), _get_weather)
```

Need secrets, routes, a settings UI, or skills? See the matching sections in
`PLUGIN-ARCHITECTURE.md` (§4–5) and copy the patterns from `plugin-render` / `plugin-files`.

## 4. Test locally

**Inner loop first — no marketplace needed.**

a) **Unit test the logic** (the template ships a passing example):
```bash
pip install -e . && pytest
```

b) **Run it inside a real Luna** to test agent behavior. Local plugins don't need a
marketplace — drop the package into your Luna's local plugins dir, restart, and chat:
```bash
cp -r weather /path/to/luna/plugins/weather   # or symlink
# restart luna serve, then ask the agent to use the tool
```
Iterate here until the agent calls your tool correctly.

## 5. Open-source it (required)

Every plugin must also be a public repo under **`github.com/huemorgan/<plugin-name>`**:

```bash
cd plugins/my-plugin
git init && git add . && git commit -m "feat: initial weather plugin"
gh repo create huemorgan/weather --public --source=. --push
git tag v0.1.0 && git push --tags
```
Link the repo from the manifest `readme` so the marketplace page points back to source.

## 6. Publish to the marketplace

Package (single top-level dir) and upload. Use the helper:
```bash
python ../../scripts/package_plugin.py weather              # -> weather-0.1.0.zip
../../scripts/publish_plugin.sh weather-0.1.0.zip my-mp     # your marketplace slug
```
- **Your own / third-party plugins** → your marketplace slug (you must own it).
- **First-party plugins** going into `official` → use the repo-seeded path in the
  `luna-marketplaces` service (see `UPDATING-A-PLUGIN.md` §"Core / repo-seeded").

## 7. Verify it installs

```bash
curl -s https://marketplaces.com.ai/mp/<slug>/index.json | python3 -m json.tool
```
Your plugin should appear in `plugins[]` with a `sha256`. Then it shows in Luna's Marketplace
pane with an Install button — install it and run the tool to confirm end to end.

---

## Conventions recap

- `luna_sdk` only — **no `import luna.*`**.
- snake_case package dir, kebab-case plugin name, they map via `entry`.
- Honest `policy` + `risk_level` per tool.
- One top-level dir in the zip.
- Public repo at `github.com/huemorgan/<name>`, tagged per version.
