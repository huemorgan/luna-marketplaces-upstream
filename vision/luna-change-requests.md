# Change Requests to the Luna Project — Marketplace Support

> Addressed to the agent/team building Luna. The Luna Marketplaces project is building an open protocol + service for distributing Luna plugins through operator-run marketplaces (see [`vision-draft.md`](./vision-draft.md)). This document lists what we need changed in Luna core to make that architecture work. Each request says **what** we need and **why**; **how** is yours to design — you own the core.

**Context you need:** a marketplace is a signed, static-hostable index of plugin versions. An agent holds an ordered list of marketplaces (often just one, often private to a company). Adding a marketplace = the owner trusting its operator, exactly like Luna's existing "install plugins from vendors you trust" model. Installs and updates are approval-gated. Compatibility between plugin versions and Luna versions is resolved *before* code loads — by the marketplace and the installer, not at runtime.

---

## CR-1 — Versioned Plugin SDK (the decoupling boundary)

**What:** Extract the plugin contract into a standalone, semver'd package (`luna-plugin-sdk` — already named in your vision.md): `LunaPlugin`, `PluginManifest`, `PluginContext` as an abstract surface, `ToolDef`, `SkillDef`, `PromptInjection`, UI declaration types, event name constants, the `ctx.approval` contract types. Luna core *implements* the SDK; out-of-tree plugins import *only* the SDK.

**Why we need it:** out-of-tree plugins cannot track a contract that versions itself through phase amendments inside your repo (005.2, 005.909, 005.916, 005.921...). The SDK's semver is the compatibility currency the whole marketplace ecosystem prices in. Our publish pipeline will lint published plugins and reject any `import luna.*` — but only you can make the SDK surface complete enough that plugins never need to.

**Scope note:** you decide which plugins are decoupled and when. We only need the boundary to exist. Migrating your in-tree plugins to import the SDK is excellent dogfooding but not our requirement.

## CR-2 — Capability Manifest per Release

**What:** Each Luna release publishes a machine-readable, signed manifest at a well-known URL: Luna version, supported SDK major(s), a map of capability versions, plus deprecations (with removal targets and migration notes) and removals. Example shape:

```json
{
  "luna_version": "0.10.0",
  "sdk_majors": [1],
  "capabilities": {
    "tools": 2, "events": 1, "prompt_fragment": 1, "skills": 1,
    "ui.iframe": 2, "ui.settings_def": 1,
    "approval.request": 2, "provider.memory": 1, "provider.vault": 1
  },
  "deprecated": { "ui.widgets": { "removal": "1.0", "note": "use ui.iframe" } },
  "removed": []
}
```

**Why we need it:** this file is what lets the ecosystem survive Luna evolving. Marketplaces ingest it and recompute compatibility for every plugin in their catalog automatically — badge deprecated paths, block incompatible installs with a stated reason, notify authors with your migration note. Plugins declare *required capabilities* in their manifest (`requires = { tools = ">=2" }`); nobody hand-maintains "works with Luna 0.6–0.9" ranges, and a release that changes the UI contract doesn't falsely break tool-only plugins.

**Discipline this implies for you:** capability versions must actually bump when the surface changes. We suggest CI that diffs the SDK public surface and fails the release if capabilities weren't updated — but again, the how is yours.

## CR-3 — Marketplace Client (`plugin_marketplace`, type `system`)

**What:** A **plugin** — `plugin_marketplace`, type `system`. "Everything is a plugin" is Luna's own first principle, and the marketplace capability is no exception. It ships by default like `plugin_memory` or `plugin_mcp`, but it's a plugin: separately versioned, replaceable, and an owner who wants an air-gapped agent with no install capability can disable it (with confirmation) and lose nothing else. It also makes the marketplace client itself updatable *through a marketplace* — the client should be able to update itself like any other plugin.

The plugin:

- Manages the agent's **ordered marketplace list**: add (fetch identity doc, show operator name + key fingerprint, pin the signing key), remove, reorder.
- Gives the agent **search/browse tools** across configured marketplaces, results grouped by marketplace in hierarchy order.
- Handles **install/update/uninstall**, writing a lockfile (in Postgres): fully-qualified plugin name (`marketplace-id/plugin-name`), exact version, artifact hash, marketplace id, pinned key, approval reference.
- Contributes the catalog/browse UI (iframe panel, per your plugin UI model) and the marketplace settings tab.
- New approval kinds, all flowing through your existing `ctx.approval` architecture: `marketplace.add`, `plugin.install`, `plugin.update`, `plugin.uninstall`. Install/update approval cards should render the plugin's permission summary — and on update, the **permissions diff** ("v2.0 newly requests: egress to api.stripe.com") since most real supply-chain attacks arrive as updates to trusted packages.

**One carve-out, following your own "engines live in plugins, gates live in core" pattern** (the same split as `plugin_approvals` vs. the core dispatch gate): the **final integrity check belongs in the core loader, not in the plugin.** At plugin-load time, core verifies the artifact on disk against the lockfile hash before executing any of it. The reason is bootstrap logic, not distrust: the marketplace plugin cannot be the integrity gate for the code path that loads plugins — it is itself loaded by that path, and it will eventually update *itself* through it. The plugin fetches, verifies-on-download, resolves, and manages state (the engine); core refuses to load anything whose hash doesn't match the lockfile (the gate). This also keeps a malicious or buggy replacement marketplace client from becoming a bypass: whatever wrote the file, core checks the hash.

**Hard rules the client must enforce (these are security invariants of the protocol, not preferences):**

1. **Updates are sticky.** A plugin installed from marketplace A can never be updated from marketplace B. No cross-marketplace version shadowing — this is the dependency-confusion defense.
2. **Verification on every fetch.** Index and artifacts verified against the pinned marketplace key; artifacts verified against the content hash in the signed metadata. Key rotation requires a signature chain from the old key or owner re-approval.
3. **Compat gate before load.** If the plugin's required capabilities aren't satisfied by the running Luna's capability manifest, the install is blocked with the reason shown. No "install and hope."

## CR-4 — Out-of-Tree Plugin Loading

**What:** The core loader loads plugins from a managed directory populated by the marketplace plugin — same lifecycle, same `PluginContext` injection, same namespace isolation and crash boundaries as in-tree plugins — and performs the lockfile hash verification described in CR-3 before executing anything. This (plus the capability-manifest publication in CR-2) is the only marketplace-related logic that lives in core; everything user-facing is `plugin_marketplace`.

**Local plugins are untouched — this must stay true.** The marketplace is an *additional* install source, never the only one. Three load paths coexist, and the first two work exactly as today, with the marketplace plugin disabled or absent:

| Source | Example | Hash-verified against lockfile? |
|---|---|---|
| **In-tree / local folder** | A developer drops a folder into `plugins/`; plugins that stay coupled to core | No — trusted because the owner put it on the machine (your existing model) |
| **Self-written** | Luna develops a plugin for itself via plugin-code (approval-gated, as you already designed) | No — born local; versioned by your Version Store as today |
| **Marketplace-installed** | Fetched into the managed directory by `plugin_marketplace` | Yes — lockfile hash check applies *only* to these |

The lockfile governs only what the marketplace installed. A plugin in the local folder needs no lockfile entry, no signature, no marketplace at all. And plugins that remain coupled to core internals simply stay in-tree — nothing forces them through the SDK or the marketplace.

**The hard sub-problem (flagging, not solving):** Python dependency isolation. Marketplace plugins will declare PyPI dependencies; two plugins will eventually want conflicting versions. Per-plugin venvs, a shared resolved environment with conflict detection at install time, or vendored deps in the artifact — your trade-off to make. We only need the chosen answer to be deterministic and to fail at *install time* (where the owner sees an approval card), never at runtime.

## CR-5 — Tier Policy & Exclusive Mode

**What:**

- `bonded` plugins are **never installable from a marketplace**. Loader-enforced, like your existing bonded rules.
- `system` / provider plugins (memory, vault implementations) install only from marketplaces the owner has marked **vetted** — a higher trust grade than merely added.
- **Exclusive mode:** an org-level policy "this agent installs only from marketplace X." This is the feature that lets companies force their fleet onto their own curated marketplace. Per your own Bonded State Principle, the marketplace list and exclusive-mode flag must have **no agent-writable tools** — owner UI or env-level config only. An agent that can be prompt-injected into adding a marketplace defeats the entire trust model.
- **Scope note:** exclusive mode constrains *marketplace* installs only. Local-folder plugins and Luna's self-written plugins (see CR-4) are outside its scope — they remain governed by your existing trust model and approval gates. (If an org someday wants to lock down local installs too, that's an org-policy feature for Luna to consider independently; the marketplace architecture neither requires nor implies it.)

## CR-6 — Conformance Suite

**What:** A test harness (`luna-plugin-conformance` or similar) with a fake Luna host — in-memory event bus, stub registries, recording approval contract — that a plugin can be run against, per SDK version. Two consumers: plugin authors in their own CI, and **our publish pipeline**, which runs it automatically against every Luna/SDK version a published plugin claims to support.

**Why you should want it too:** running the same suite against Luna itself is what turns "Luna 0.10 supports SDK 1.x" from a changelog sentence into a verified claim.

## CR-7 — Security Doc Amendment

**What:** `vision/security.md` currently says there is "no community plugin marketplace, no 'install this random plugin from the internet.'" That sentence rejects **trustless** distribution, and it should stay rejected. Marketplaces are **trustful** distribution: the owner trusts a named operator (their company, their vendor, or the official marketplace's operator) exactly as they'd trust a plugin vendor today — and the protocol makes the channel tamper-evident (signing, key pinning, content addressing, transparency log). Please amend the doc to state the marketplace trust model explicitly so the two projects don't appear to contradict each other: *trust is established at "add marketplace" time, per operator; the trust boundary at install time is unchanged.*

---

## Priority order from our side

| Order | CR | Unblocks |
|---|---|---|
| 1 | CR-1 (SDK) | Everything — without a boundary there is nothing to distribute |
| 2 | CR-3 + CR-4 (client + loader), prototype quality | Our M1: one real plugin, installed from a static signed index into a real agent |
| 3 | CR-2 (capability manifest) | Our M3: compat watch, automated catalog re-evaluation |
| 4 | CR-6 (conformance) | Publish-time verification in our service |
| 5 | CR-5 (tiers/exclusive) + CR-7 (docs) | Enterprise story; can land with your normal release cadence |

For M1 we don't need polish — a hardcoded-path loader and a CLI-only client behind a flag is enough to prove the loop: `luna-mp build` a static marketplace → agent adds it → searches → installs → plugin passes the same dojo tests it passed in-tree.

---

## What we provide in return

- The **protocol spec** (identity doc, signed index, versions files, artifact envelope) — co-designed with you, versioned, with a reference static implementation (`luna-mp build`).
- The **publish pipeline** that enforces SDK-only imports, manifest validity, semver, signing — so out-of-tree quality is policed at distribution time, not in your repo.
- **Compat watch** — when you release, we re-test the whole ecosystem against your capability manifest and tell every affected author what to fix, citing your migration notes. Your release-breakage guilt is our product feature.
