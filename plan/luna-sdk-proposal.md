# `luna-plugin-sdk` — A Concrete Proposal for the Luna Project

> Companion to [`../vision/luna-change-requests.md`](../vision/luna-change-requests.md) CR-1. That doc says *what* we need and why; this one is our **suggestion** for how to structure it. You own the core — take, adapt, or counter-propose. Written after reading your `vision/plugin-architecture.md`, `luna/plugins/base.py`, and the in-tree plugins.

**The one-sentence idea:** move the *contract* (types, protocols, constants) into a separately versioned package that both Luna core and out-of-tree plugins depend on — and make the SDK the single source of truth from which the capability manifest (CR-2) is generated.

---

## 1. Goals / Non-Goals

**Goals**
- A plugin can be written, tested, and published against the SDK alone — no `import luna.*`.
- Semver on the contract: plugins and hosts that release on different schedules can still reason about compatibility.
- The capability manifest (CR-2) is *generated from* the SDK, not hand-maintained.
- Your in-tree plugins use the same SDK (dogfooding) — but on your schedule; nothing breaks if they migrate gradually.

**Non-goals**
- Moving any *implementation* out of core. The SDK has near-zero runtime logic.
- Forcing decoupling. Coupled plugins stay in-tree and may keep importing core internals indefinitely.
- A new plugin model. This is your existing contract, re-homed and versioned.

---

## 2. What Goes In (mapped from your current code)

Everything a plugin author touches today in `luna/plugins/base.py` and friends — types only, implementations stay in core:

| SDK module | Contents | Today lives in |
|---|---|---|
| `luna_sdk.plugin` | `LunaPlugin` base class, lifecycle hook signatures (`on_load`, `on_event`, `prompt_fragment`...) | `luna/plugins/base.py` |
| `luna_sdk.manifest` | `PluginManifest`, `PluginType`, `ToolDef`, `SkillDef`, `SidebarSection`, `SettingsTab`, `SettingsDef`, `SettingsField`, `WidgetSlot`, license/entitlement fields | `luna/plugins/base.py` |
| `luna_sdk.context` | `PluginContext` as a **`typing.Protocol`** — the full `ctx.*` surface (`db_session_factory`, `events`, `tool_registry`, `provider_registry`, `vault`, `memory`, `router`, `approval`, `tasks`, `agent`) as abstract interfaces | implicit in core today |
| `luna_sdk.approval` | The `ctx.approval.request(...)` contract types: request params, `Decision`, renderer registration types, risk levels | `plugin_approvals` / core contract |
| `luna_sdk.prompt` | `PromptInjection`, layer names, priority conventions | plugin-architecture.md §3 |
| `luna_sdk.events` | **Event name constants** (`tool.completed`, `llm.called`, `approval.decided`...) + payload TypedDicts | scattered strings today |
| `luna_sdk.providers` | `MemoryProvider`, `VaultProvider` ABCs | core |
| `luna_sdk.results` | `ToolResult`, `ChatComponent` and the component-type names | core |
| `luna_sdk.capabilities` | See §4 — the capability registry | doesn't exist yet |
| `luna_sdk.testing` | Fake host for plugin unit tests (in-memory event bus, recording approval stub, stub registries) — the seed of the CR-6 conformance kit | doesn't exist yet |

**Key choice — `PluginContext` as Protocol, not ABC:** core's real context object doesn't need to inherit from anything; it just satisfies the Protocol. Plugins type against the Protocol; you keep full freedom inside core. Mypy enforces both sides honestly.

**What stays out:** the loader, namespace-enforcing session factory, gate/dispatch code, prompt assembler, provider registry implementation, anything Postgres/Redis/DBOS. A plugin importing the SDK pulls in pydantic and nothing else heavy.

---

## 3. Versioning Policy (the part that matters most)

- **Semver, strictly mechanical:**
  - **Major** — any breaking change to an existing type/protocol (removed field, changed signature, narrowed type).
  - **Minor** — additive: new optional manifest fields, new event constants, new capability versions, new protocol members *with defaults*.
  - **Patch** — docs, fixes with no surface change.
- **The SDK major is the ecosystem's coarse compatibility gate** (a plugin built for SDK 1 never loads on a host implementing only SDK 2). Spend majors *very* slowly — target: years. The phase-amendment churn that's normal inside your repo (005.909, 005.916, 005.921...) must land as **minors** in the SDK, which means: new surfaces arrive optional-first, old surfaces deprecate with warnings for at least one minor before a major removes them.
- **Host declares implemented range** — Luna core declares `implements_sdk = ["1.x"]`; during a major transition, core can implement two majors simultaneously (the types can coexist under `luna_sdk` v2 re-exporting v1 compat shims), giving plugin authors a real migration window.
- **CI guard:** a public-surface diff (e.g. griffe) runs on every SDK PR and fails if the surface changed without the right version bump. This is what makes the semver promise mechanical instead of aspirational.

---

## 4. The Capability Registry (how CR-1 feeds CR-2)

Our suggestion for making the capability manifest non-hand-maintained:

```python
# luna_sdk/capabilities.py — THE registry, in code, reviewed like code
CAPABILITIES: dict[str, int] = {
    "tools": 2,            # ToolDef + policy semantics
    "events": 1,           # event bus subscription/emission
    "prompt_fragment": 1,  # PromptInjection contract
    "skills": 1,           # SkillDef + load_skill
    "ui.iframe": 2,        # sidebar_sections + /api/p/{name}/ui/ contract
    "ui.settings_def": 1,  # declarative settings forms
    "approval.request": 2, # ctx.approval contract incl. edit_schema
    "provider.memory": 1,
    "provider.vault": 1,
    "routes": 1,           # routes_module / register_routes contract
}
DEPRECATED: dict[str, Deprecation] = {
    "ui.widgets": Deprecation(removal_sdk_major=2, note="use ui.iframe"),
}
```

- Each capability maps to a defined slice of the SDK surface (documented next to the constant).
- A PR that changes the `ui.iframe` contract **must** bump `"ui.iframe"` in the same diff — enforceable by the same surface-diff CI.
- Luna's release pipeline generates the CR-2 manifest mechanically: SDK majors implemented + this dict + the release version, signed. No human writes the manifest.
- Plugin manifests declare `requires = { "tools": ">=2" }`; both your install-time gate (CR-3 rule 3) and our marketplace compat matrix evaluate against the same dict.

---

## 5. Extraction Mechanics (lowest-risk path)

1. **Monorepo package, not a new repo:** `packages/luna-plugin-sdk/` inside the `luna` repo, own `pyproject.toml`, published to PyPI independently. Atomic PRs across core+SDK while the contract stabilizes; you can split the repo later if ever worth it.
2. **Move types, re-export from old paths:** `luna/plugins/base.py` becomes `from luna_sdk.manifest import *` shims with a deprecation comment. In-tree plugins keep working untouched; they migrate imports opportunistically.
3. **Core depends on the SDK** like any consumer. The moment of truth: anything core needs that isn't in the SDK is either (a) genuinely internal — fine, or (b) something plugins also need — move it in.
4. **Lint the boundary:** in-tree, an import-linter contract ("plugins may not import `luna.*` except via SDK") with a per-plugin allowlist that starts full and shrinks as plugins migrate — the allowlist *is* your decoupling progress dashboard. Out-of-tree, our publish pipeline enforces the same rule with no allowlist.
5. **`luna plugin init`** (already in your vision) scaffolds against the SDK + `luna_sdk.testing` from day one, so every new plugin is born decoupled.

Suggested first migrations to validate the surface: `plugin_charts` (tools only — trivial), then `plugin_files` (UI + routes — exercises the iframe and routes contracts). If those two migrate cleanly, the SDK surface is probably right.

---

## 6. The Testing Story (`luna_sdk.testing` → conformance)

Ship a fake host with the SDK from v0:

```python
from luna_sdk.testing import FakeHost

async def test_my_plugin():
    host = FakeHost()                       # in-memory bus, stub registries,
    plugin = MyPlugin()                     # recording approval (auto-approves,
    await host.load(plugin)                 # records every request)
    result = await host.call_tool("my_tool", {"x": 1})
    assert host.approvals.requested[0].kind == "tool_call"
```

This grows into the CR-6 conformance suite: the same scenarios, parameterized per SDK version, runnable by plugin authors in their CI and by our publish pipeline. And running the suite against *real* Luna instead of `FakeHost` is what verifies "Luna 0.10 implements SDK 1.x" as a tested claim rather than a changelog line.

---

## 7. Open Items (your call, we just need an answer)

1. **Pydantic version policy** — the SDK pins a pydantic major; that pin propagates to every plugin. v2-only seems obvious today; worth stating explicitly.
2. **`ctx.agent.run_turn` in v1?** — powerful but the least stable surface. Option: ship it behind `luna_sdk.experimental` with no semver promise until it settles.
3. **Event payload typing depth** — full TypedDicts per event (best DX, more surface to maintain) vs. constants + documented dicts (less commitment). We lean full typing for the ~10 core events, constants-only for the long tail.
4. **Where does the JSON Schema for the *published* manifest live?** Our protocol spec (phase 001) defines the published form; ideally it's generated from `luna_sdk.manifest` models so the two can't drift. Happy to wire our spec build to import your SDK for schema generation.
