# Luna Marketplaces — High-Level Plan

> The phase sequence for building the marketplace protocol and service, derived from [`../vision/vision-draft.md`](../vision/vision-draft.md). Each phase gets its own folder here (`plan/NNN-phase-name/PLAN.md`) written **before** implementation starts. This file is the map; the phase plans are the territory.

**Convention** (mirrors the Luna project): `NNN-name/PLAN.md`. Point-releases for fixes/amendments as `NNN.M-name`.

---

## Phase Sequence

| Phase | Name | One-liner | Depends on Luna? |
|---|---|---|---|
| **001** | `protocol-spec` | The open protocol v0 + reference static tooling (`luna-mp`) | No |
| **002** | `luna-e2e-proof` | One real plugin, published → added → installed → passing dojo in a real agent | Yes (CR-1, CR-3, CR-4 prototypes) |
| **003** | `service-mvp` | Accounts, orgs, marketplaces, publishing — the hosted service skeleton | No |
| **004** | `catalog-and-curation` | Public catalog UI, plugin pages, curation workflow | No |
| **005** | `compat-watch` | Capability-manifest ingestion, compat matrix, conformance runs at publish | Yes (CR-2, CR-6) |
| **006** | `trust-infrastructure` | Transparency log, directory service, verified publishers, channels | No |
| **007** | `pricing` | Switch on plans + billing (designed since 003, enforced here) | No |

Phases 003+ can start before 002 completes if Luna-side work stalls — the service is useful to vendors building plugin sets even before agent-side install is polished. But **002 is the moment of truth** and stays the priority signal: if the e2e loop doesn't work, everything after it is decoration.

---

## Phase 001 — `protocol-spec`

**Goal:** the marketplace format exists as a precise, open, statically-implementable spec — with working reference tooling proving it.

**Includes:**
- Protocol spec documents: identity document (`/.well-known/luna-marketplace.json`), signed index, per-plugin versions file, published-manifest schema, artifact envelope (zip + hash + signatures), naming/namespacing rules, freshness (timestamp) and rollback-protection rules.
- JSON Schemas for every document; canonical test vectors (valid + deliberately-tampered fixtures).
- `luna-mp` reference CLI: `keygen`, `build` (folder of plugins → complete static marketplace), `verify` (full integrity audit of a marketplace), `serve` (local dev server).
- A sample marketplace with two dummy plugins, built and verified in CI.

**Deliverable:** a third party could implement a compatible marketplace from the spec alone; `luna-mp verify` catches every tamper class we claim to defend against.

**Detailed plan:** [`001-protocol-spec/PLAN.md`](./001-protocol-spec/PLAN.md) ← written

---

## Phase 002 — `luna-e2e-proof`

**Goal:** prove the decoupled loop end to end with the Luna project.

**Includes:**
- Coordinate with the Luna agent on prototype versions of CR-1 (SDK), CR-3 (`plugin_marketplace`), CR-4 (out-of-tree loader). Prototype quality is fine: CLI-only client behind a flag, hardcoded managed directory.
- Pick the proof plugin — `plugin_charts` (leaf, tools-only) or a knowhow pack (no code at all; possibly even easier — decide at phase start).
- Publish it with `luna-mp build`, host statically, add the marketplace to a real agent (key pinned, approval-gated), search, install, run the same dojo tests it passed in-tree.
- Negative tests: tampered artifact rejected by core loader, stale timestamp rejected, cross-marketplace update refused.

**Deliverable:** a recorded dojo run of the full loop + a written gap list feeding Luna's CRs and our spec v0.1 amendments.

---

## Phase 003 — `service-mvp`

**Goal:** the hosted service skeleton at `marketplaces.com.ai` — operators can run marketplaces without self-hosting.

**Includes:**
- Accounts & orgs: signup, org creation, member roles (owner/publisher/reviewer/viewer). From day one: `plan` field on org (everyone `free`), single `org_can(org, feature)` gate, usage-event recording (publishes, downloads, distinct pulling agents) — pricing structurally present, not enforced (vision §7).
- Marketplace management: create/configure marketplaces per org; public/unlisted/private; `{slug}.marketplaces.com.ai` subdomains; token auth for private marketplaces.
- Publishing: `luna-mp publish` against the service API; server-side validation (manifest, semver, SDK-import lint); immutable versions (yank, never overwrite); signed index regeneration; artifact storage (content-addressed).
- The service serves the *same protocol* as a static marketplace — it must pass `luna-mp verify` like any other implementation.

**Deliverable:** a vendor signs up, creates a private marketplace, publishes a plugin, and a client agent installs from it with a token.

---

## Phase 004 — `catalog-and-curation`

**Goal:** the marketplace becomes browsable and curatable — the operator's product surface.

**Includes:**
- Public catalog UI: browse/search, plugin pages (README, version history, permissions summary, publisher identity, download stats).
- Org dashboard: members, marketplaces, plugins, publish history, token management.
- Curation workflow: publisher submits → reviewer approves → visible to agents. Per-marketplace toggle (solo operators skip it).
- Namespace policy enforcement: reserved prefixes (`luna-*`, `official-*`), lookalike-name warnings (edit-distance), dispute process documented.

**Deliverable:** the public marketplace at `official.marketplaces.com.ai` is a place a human can evaluate a plugin before approving its install.

---

## Phase 005 — `compat-watch`

**Goal:** the ecosystem survives Luna evolving — compatibility is computed, not promised.

**Includes:**
- Ingest Luna's signed capability manifests (CR-2) on release.
- Compute and display the compat matrix (plugin version × Luna capability set) on every plugin page; badge deprecated-path and incompatible statuses.
- Author notifications on new deprecations affecting their plugins, citing Luna's migration notes.
- Publish-time conformance runs (CR-6 suite) against every Luna/SDK version a plugin claims; results shown in catalog.
- Install-time compat data exposed through the protocol so the agent-side gate (CR-3 rule 3) has what it needs.

**Deliverable:** a Luna release triggers automatic catalog re-evaluation; affected authors are notified within the hour; agents are blocked from incompatible installs with stated reasons.

---

## Phase 006 — `trust-infrastructure`

**Goal:** trust at scale — tamper-evidence beyond a single marketplace's honesty.

**Includes:**
- Transparency log: append-only Merkle log of every (marketplace, plugin, version, hash); public monitor endpoint.
- Directory service: any marketplace (including self-hosted) registers `(id, url, key)`; Luna clients cross-check pinned keys. Optional by protocol design — the centralization line from vision §8.2 gets settled here.
- Verified publisher program: domain/org verification, checkmark in catalog.
- Key rotation flows (signature chain from old key; owner re-approval path).
- Release channels per plugin: `stable` / `beta` / `nightly`.

**Deliverable:** hijacking a marketplace requires compromising the marketplace AND the directory AND going undetected by the transparency log.

---

## Phase 007 — `pricing`

**Goal:** turn on the business — without ever having to re-architect for it.

**Includes:**
- Pick the paid axes from vision §7.2 (leading candidate: private marketplaces + seats as the primary line).
- Billing integration, plan upgrade/downgrade, usage dashboards from the metering data collected since 003.
- Enforcement via the existing `org_can()` gate — flipping features per plan, no structural change.
- Explicitly still deferred: paid-plugin payment rail / entitlement issuing (vision §7.3).

**Deliverable:** paying customers; free tier and self-hosters unaffected; trust-critical features free on every tier (vision §7.4).

---

## Standing Documents

- [`../vision/vision-draft.md`](../vision/vision-draft.md) — the why and the what
- [`../vision/luna-change-requests.md`](../vision/luna-change-requests.md) — what we need from Luna (CR-1…CR-7)
- [`luna-sdk-proposal.md`](./luna-sdk-proposal.md) — our concrete suggestion for how Luna structures the plugin SDK (CR-1 elaborated)
