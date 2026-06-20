# Luna Plugin Architecture

> The mental model an agent (or human) needs before touching plugin code.
> Read this first; the create/update/setup docs assume it.

---

## 1. What a Luna plugin *is*

Luna is a thin agent core surrounded by plugins. **A plugin is a self-contained Python
package that registers capabilities (tools, skills, routes, UI, settings) with the host
at load time.** It is authored against **`luna_sdk` only** — it never does `import luna.*`.
That single rule is what makes a plugin portable: it can be packaged, hosted in a
marketplace, fetched by any Luna agent, hash-verified, and loaded.

Two artifacts define every plugin:

| File | Who reads it | Purpose |
|---|---|---|
| `luna-plugin.toml` | the marketplace + Luna's installer, **without importing Python** | the **data manifest**: identity, version, capabilities, tools, readme |
| `<package>/__init__.py` | the Luna runtime, at load time | the **code**: a `LunaPlugin` subclass that registers capabilities |

The manifest is "manifest-as-data": tooling can read what a plugin needs *before* running
any of its code. Keep the two in sync (same `name`, `version`, tool list).

---

## 2. Anatomy of a plugin package

```
my_plugin/
  __init__.py          # required — the LunaPlugin subclass
  luna-plugin.toml     # required — the data manifest
  client.py            # optional — your own modules, imported relatively
  routes.py            # optional — FastAPI routes (referenced by routes_module)
  state.py             # optional — module-level state
  ui/                  # optional — static assets for a standalone UI
  interface/webui/...  # optional — settings-tab iframe content
```

The **package directory name** (e.g. `my_plugin`) is the `entry` in the manifest and the
single top-level directory inside the published zip.

---

## 3. The `LunaPlugin` lifecycle

```python
from luna_sdk import LunaPlugin, PluginContext, PluginManifest, ToolDef

class MyPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="my-plugin",        # kebab-case identity (matches toml)
        version="0.1.0",
        description="What it does.",
    )

    async def on_load(self, ctx: PluginContext) -> None:
        # Register everything here. Called once when the agent loads the plugin.
        ...

    async def on_unload(self) -> None:
        # Optional. Release resources (close clients, etc.).
        ...
```

- **`on_load(ctx)`** is the entry point. Everything a plugin exposes is registered through
  `ctx` here.
- **`on_unload()`** is for cleanup (closing HTTP clients, etc.).
- The class-level `manifest` is the runtime mirror of `luna-plugin.toml`.

---

## 4. What a plugin can register (the capability surface)

Through `PluginContext` (`ctx`) in `on_load`:

### Tools — functions the agent can call
```python
ctx.tool_registry.register(
    self.manifest.name,
    ToolDef(
        name="my_tool",
        description="What it does (the agent reads this to decide when to call it).",
        parameters={  # JSON Schema for the arguments
            "type": "object",
            "properties": {"name": {"type": "string", "description": "..."}},
            "required": [],
        },
        policy="auto_approve",   # see policy table below
        risk_level="low",        # low | medium | high
    ),
    _my_tool_handler,            # async def returning a JSON-serializable dict
)
```

### Skills — bundles of tools gated behind a capability the agent can "learn"
```python
ctx.skill_registry.register(self.manifest.name, SkillDef(
    name="my-skill",
    description="What becoming skilled unlocks.",
    body="Instructions injected when the skill is active.",
    tools=["my_tool", "my_other_tool"],
))
```
Register tools with `skill_gated=True` to keep them hidden until the skill is active.

### Routes — backend HTTP endpoints
Set `routes_module="routes"` in the manifest and put a FastAPI router in `routes.py`.
Served under `/api/p/<plugin-name>/...`. Auth-gate with the SDK's `get_current_user`.

### Settings tab + UI — a themed iframe in Luna's Settings
```python
manifest = PluginManifest(
    ...,
    settings_tabs=[SettingsTab(id="render", label="Render", icon="cloud",
                               sort_order=70, iframe_src="/api/p/plugin-render/ui/settings/")],
    interfaces={"webui": "interface/webui"},
)
```

### Secrets — via the vault provider
```python
cred = await ctx.vault.get_credential("my_plugin.api_key")  # raises KeyError if unset
api_key = cred.value
```
Declare the dependency: `depends_on=["plugin-vault"]` (manifest) so load order is correct.

---

## 5. Tool policy & risk (the trust controls)

Every tool declares how much human oversight it needs. Set these honestly — they drive
Luna's approval UX.

| `policy` | Meaning |
|---|---|
| `auto_approve` | runs without asking (safe, read-only-ish) |
| `ask` | asks for approval once / per session |
| `prompt_always` | asks every single call (destructive or sensitive) |

| `risk_level` | Use for |
|---|---|
| `low` | reads, lists, idempotent fetches |
| `medium` | state changes that are recoverable (restart, trigger deploy) |
| `high` | destructive / sensitive (delete, suspend, set secret) |

Use `sensitive_args=["value", "token"]` on `ToolDef` to keep secret arguments out of logs.

**Rule of thumb:** read = `auto_approve`/`low`; write = `ask`/`medium`; delete or secrets =
`prompt_always`/`high`.

---

## 6. Plugin shapes, by example

Real plugins in the official marketplace, from simplest to richest:

- **`hello-world`** — a *leaf*: one tool, no deps, no routes, no UI. The minimal plugin.
- **`plugin-files`** — tools + backend `routes.py` + a standalone `ui/` file browser.
- **`plugin-render`** — a *connector*: 12 tools grouped into skills, a settings-tab iframe,
  `depends_on=["plugin-vault"]` for the API key, lifecycle cleanup in `on_unload`.

Study these as references — the create doc points back to them.

---

## 7. Packaging & the trust gate

When published, the package is zipped (one top-level dir) and **content-addressed by the
SHA256 of the zip bytes**. The marketplace catalog (`index.json`) lists that hash.

> **The hard rule:** `sha256` in `index.json` must equal the hash of the served artifact
> bytes. Luna refuses to load on mismatch. This is the entire trust mechanism — you trust a
> marketplace's publisher, and the hash guarantees the bytes didn't change in transit.

You never compute hashes by hand — the service does it on publish. Don't hand-edit artifacts.

---

## 8. The v0 marketplace protocol (what Luna fetches)

A marketplace is just three URLs under a root (`https://<host>/mp/<slug>/`):

| Path | Returns |
|---|---|
| `GET .../.well-known/luna-marketplace.json` | identity `{id, name, protocol_version}` |
| `GET .../index.json` | catalog `{marketplace, protocol_version, plugins:[{name, version, description, sdk_version, requires, artifact, sha256}]}` |
| `GET .../plugins/{name}/{version}/artifact.zip` | the plugin zip |

The official marketplace root is **`https://marketplaces.com.ai/mp/official/`**. A user pastes
that into Luna → **Settings → Marketplaces**, and Luna reads `index.json` to build the list.

---

## 9. Versioning rules

- Versions are **semver** and **immutable**: once `my-plugin@0.1.0` is published, those bytes
  are frozen. Re-publishing the same `name@version` with different bytes is rejected (409).
- To ship a change you **bump the version** (in *both* `luna-plugin.toml` and the
  `PluginManifest`) and publish again. See `UPDATING-A-PLUGIN.md`.

---

## 10. The non-negotiables (checklist)

- [ ] Authored against `luna_sdk` only — **no `import luna.*`**.
- [ ] `luna-plugin.toml` and `PluginManifest` agree on `name`, `version`, tools.
- [ ] One top-level package dir; `entry` matches that dir name.
- [ ] Every tool has an honest `policy` + `risk_level`.
- [ ] Secrets come from the vault, never hard-coded.
- [ ] The plugin also lives as a public repo at `github.com/huemorgan/<plugin-name>`.
