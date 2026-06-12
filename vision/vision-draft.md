# Luna Marketplaces — Vision Draft

> A service for creating and operating marketplaces of Luna plugins. The marketplace **format/protocol is open**; the **service code is proprietary**. Anyone can implement a marketplace; we run the best one — at `marketplaces.com.ai`.

**Status:** draft for discussion. This document collects ideas, considerations, and open questions — not final decisions.

**Companion doc:** [`luna-change-requests.md`](./luna-change-requests.md) — what we need the Luna project to change to support the marketplace architecture. Decoupling plugins from the Luna core is **Luna's responsibility**; that doc is our formal request to them. This doc is about **our** project: the protocol and the service.

---

## 1. Why This Project Exists

Luna today ships its plugins inside the core repo. That works for a small project, but it caps the ecosystem:

- **Companies** building on Luna want private plugins their agents can install — without forking Luna or publishing their code.
- **Vendors/integrators** deploying Luna for client orgs want to hand the client a marketplace link: "here are the plugins we built and maintain for you."
- **The Luna project itself** wants a smaller core repo: fewer in-tree plugins, faster releases, plugins evolving on their own cadence.
- **Agent owners** want to browse, search, install, and update plugins from inside Luna — from one or many marketplaces.

### Division of responsibility

| | Owned by |
|---|---|
| Decoupling plugins from core (SDK, contract, which plugins move out and when) | **Luna project** |
| Capability/compatibility manifests published per Luna release | **Luna project** (format co-designed with us) |
| Marketplace client inside Luna (add marketplace, search, install, update) | **Luna project** (spec'd by us) |
| The marketplace protocol spec (open) | **This project** |
| The marketplace service: accounts, publishing, catalogs, signing, compat checks | **This project** |
| Security of the distribution channel (anti-hijack, anti-tamper) | **This project** |

Not all Luna plugins are decoupled today — some are deeply tied to core (bonded, system apps). That's fine and expected: **Luna moves the decoupled ones first, on their schedule.** Our service must be ready before they move, and must work even while most plugins are still in-tree.

**The marketplace is an additional install source, never the only one.** Local plugins stay first-class: a developer dropping a folder into `plugins/`, Luna writing a plugin for itself via its coding capability, and coupled plugins living in-tree all keep working exactly as today — no lockfile, no signature, no marketplace required. Nothing in this project may break that.

---

## 2. The Actors

| Actor | Wants | Pushes changes by |
|---|---|---|
| **Luna core maintainers** | Small core, freedom to evolve, no ecosystem breakage guilt | Releasing Luna versions + a machine-readable compatibility manifest per release |
| **Plugin authors** (community or in-house) | Write once, run on many Luna versions, get distribution | Publishing plugin versions to one or more marketplaces |
| **Marketplace operators** (companies, vendors, us) | Curate a trusted set of plugins, control what their agents can run | Approving/curating plugin versions into their marketplace; running compat checks |
| **Vendors / integrators** | Deploy Luna for orgs, ship their own plugin set, keep maintenance revenue | Operating a marketplace per client (or one marketplace, many clients) |
| **Agent owners / org admins** | Safe install, easy update, no surprises | Adding marketplaces to their agent, approving installs/updates |
| **The agent itself (Luna)** | Find a capability it lacks, propose installing it | Searching its configured marketplaces; install is approval-gated |

The interesting dynamic: **everyone moves at a different speed.** Luna core releases monthly-ish; an enterprise plugin author updates twice a year; an agent owner updates whenever. The protocol must absorb that drift instead of shattering.

---

## 3. The Trust Model (read this before the security section)

Luna's `security.md` says: *installed plugins are trusted — you install plugins you wrote, plugins from vendors you trust, or plugins you've read the source of.* The marketplace **keeps exactly that model** and extends it one level up:

> **Adding a marketplace = trusting its operator.** Same decision as trusting a vendor. If you don't trust the marketplace provider, don't add their marketplace. There is no "random plugins from the internet" — there are *operators you chose to trust*, distributing plugins through a channel we make tamper-proof.

Three consequences:

1. **The marketplace transmits trust; it doesn't create it.** A plugin from `acme-internal` is trusted because you trust Acme — not because our service scanned it. Scans, conformance runs, and permission summaries help the operator curate and the owner decide, but the decision is human and vendor-shaped.
2. **Our security obligation is channel integrity.** Once you've trusted an operator, the plugin that arrives at your agent must be *exactly* the one that operator published — despite hijacked DNS, compromised CDNs, stale caches, or a lookalike marketplace. That's §8.
3. **Curation is the operator's product.** An enterprise marketplace is a curated allowlist with a human reviewer inside the company. The public marketplace we run is *our* curation under *our* name — we are the vendor users trust when they add it.

This also resolves the apparent conflict with Luna's "no community plugin marketplace" stance: that sentence rejects *trustless* distribution. Marketplaces here are *trustful* distribution — vendor trust, made portable and tamper-evident. Luna's security doc should be amended to say this (see change requests, CR-7).

---

## 4. Decoupling: What We Depend On (summary)

Full detail lives in [`luna-change-requests.md`](./luna-change-requests.md). The short version of what the marketplace architecture needs from Luna:

1. **A versioned plugin SDK** — plugins import a semver'd `luna-plugin-sdk`, never `luna.*` internals. The SDK version is the compatibility currency between plugins and hosts that release on different schedules.
2. **A capability manifest per Luna release** — machine-readable, signed, listing capability versions (`tools@2`, `ui.iframe@2`, `approval.request@2`...), deprecations, removals. This is how the marketplace computes compatibility *for* authors and owners.
3. **A marketplace client in Luna** — itself a plugin (`plugin_marketplace`, type `system` — "everything is a plugin" applies to the marketplace too); manages the marketplace list, searches, installs, updates; every consequential step approval-gated. Only the final lockfile-hash check at load time lives in core (a plugin can't be the integrity gate for the path that loads plugins, including its own updates).
4. **Out-of-tree plugin loading** — the core loader loads plugins from a managed directory, verifies them against the lockfile, with dependency isolation.
5. **Plugin tiers respected** — `bonded` plugins never come from marketplaces; `system`/provider plugins only from operator-vetted ones.

A note on versioning, since it shapes our catalog: plugins should declare the **capabilities they need**, not Luna version ranges they bless. A Luna release that changes the UI iframe contract shouldn't flag a tools-only plugin as broken. Old plugins never need to "understand" new Luna at runtime — **the marketplace and the installer resolve compatibility before code ever loads.** Version ranges remain a display shortcut we compute from capability data.

### The drift lifecycle, end to end

1. Luna 0.10 ships; its capability manifest deprecates `ui.widgets@1` with a removal target of 1.0.
2. Every marketplace ingests the manifest (published at a well-known URL, signed).
3. Marketplace CI re-evaluates its catalog: plugins using `ui.widgets` get a **compat status: deprecated-path** badge; their authors get notified with the migration note from the manifest.
4. Agents on Luna 0.10 still install those plugins (deprecated ≠ broken). Agents that upgrade to Luna 1.0 see them as **incompatible** and are *blocked from installing*, with the reason shown.
5. Author publishes 2.0.0 of the plugin against `ui.iframe@2`. Old version stays in the catalog for agents on old Luna versions. **Both versions coexist** — the catalog is a matrix (plugin version × Luna capability set), not a list.

---

## 5. The Marketplace Protocol (open format)

### 5.1 Design stance

Like the Luna cross-agent protocol: the **wire format is open and documented**; implementations compete. A marketplace is, at minimum, **a signed static index over HTTPS** — implementable with a folder of files on any web host. Our service is one (managed, featureful) implementation. This is the apt/cargo/OCI lineage, and it's deliberately boring.

### 5.2 Minimum protocol surface

```
GET /.well-known/luna-marketplace.json     # marketplace identity + root key + endpoints
GET /index.json                            # signed: list of plugins, latest versions, compat summaries
GET /plugins/{name}/versions.json          # signed: all versions, capability requirements, hashes
GET /plugins/{name}/{version}/manifest     # the plugin manifest as published
GET /plugins/{name}/{version}/artifact     # the package itself (content-addressed; hash in versions.json)
GET /search?q=...                          # OPTIONAL — rich implementations only; agents fall back to index scan
```

- **Identity document** (`/.well-known/...`) carries: marketplace id (UUID + display name), public signing key(s), protocol version, optional org metadata, optional auth requirements (private marketplaces).
- Everything signed; artifacts content-addressed (sha256 in the signed metadata). A mirror or CDN can serve artifacts; signatures travel with metadata.
- **Private marketplaces** = same protocol + bearer token / mTLS. A vendor gives a client org a URL + token. Nothing else changes.
- Static-hostable on purpose: a company can run `luna-mp build ./plugins/ -o ./public/` and push to an S3 bucket. The protocol must never require dynamic compute — that's what keeps it open in practice, not just on paper.

### 5.3 Plugin manifest additions (published form)

```toml
[plugin]
name = "charts"
namespace = "luna-official"        # see §5.4 — namespaces are security-relevant
version = "1.4.2"                   # semver, enforced
license = "MIT"                     # or Commercial + entitlement (already in Luna's model)

[compat]
sdk = "^1.2"
requires = { tools = ">=2", events = ">=1" }

[provenance]
source = "https://github.com/huemorgan/luna-plugin-charts"
publisher_key = "ed25519:AAAA..."   # see §8
```

### 5.4 Namespaces and the hierarchy of marketplaces

The agent holds an **ordered list of marketplaces** (a hierarchy, with teeth):

```toml
[[marketplaces]]
id = "acme-internal"          # added first = highest priority
url = "https://plugins.acme.com"
pinned_key = "ed25519:..."

[[marketplaces]]
id = "luna-official"
url = "https://official.marketplaces.com.ai"
pinned_key = "ed25519:..."
```

**The hard-won lesson from npm/PyPI: name resolution across registries is the #1 attack surface (dependency confusion).** If an agent searches "charts" and two marketplaces both have it, "first wins" is how internal plugin names get hijacked by lookalikes on a public marketplace. So:

- Every installed plugin is recorded with its **fully-qualified name**: `acme-internal/charts`, not `charts`. Updates only ever come from the same marketplace.
- Bare-name search returns results *grouped by marketplace, in hierarchy order*, and install of a bare name from anything but the top match requires explicit qualification.
- A marketplace **cannot satisfy an update for a plugin installed from another marketplace.** Ever. No "we also have version 99.0 of that."
- Org policy can enforce **exclusive mode**: "this agent may only install from `acme-internal`" — this is the "companies forcing their agents to use only their marketplace" requirement, and it should be a *bonded-style policy* in Luna (agent can't switch it off; owner UI or env-level config only).

### 5.5 The lockfile

The agent keeps a lockfile (in Postgres, naturally — Luna's "DB is the brain"): plugin fully-qualified name, exact version, artifact hash, marketplace id, pinned marketplace key at install time, install approval reference. Cloning an agent (Luna's plugin-clone) carries the lockfile, so a clone can re-fetch identical plugins — this makes agent cloning work across machines without copying plugin code.

---

## 6. The Marketplace Service (our product)

What `marketplaces.com.ai` actually sells: **the protocol is free; the operating burden is the product.**

### 6.1 Core features

- **Accounts & orgs** — sign up, create org, invite members with roles (owner / publisher / reviewer / viewer).
- **Marketplaces** — an org creates one or more marketplaces. Public, unlisted, or private (token/SSO-gated). Each gets `{slug}.marketplaces.com.ai` + optional custom domain (with our verification flow, see §8.4).
- **Plugin publishing** — CLI-first (`luna-mp publish`), web upload as fallback. Every version immutable once published (yank, never overwrite — the npm left-pad lesson).
- **Automated checks on publish** (the value-add a static host can't match):
  - manifest validation, semver enforcement, SDK import lint
  - conformance suite run against every Luna/SDK version the plugin claims (suite provided by the Luna project — see change requests)
  - static security scan (secrets in code, suspicious egress, obfuscated payloads)
  - compatibility matrix computed and published
- **Catalog UI** — browse, search, plugin pages with README, versions, compat matrix, permissions summary ("this plugin declares 3 gated tools, requests vault access, egress to api.stripe.com"), publisher identity, download stats.
- **Compat watch** — when a new Luna capability manifest lands, re-evaluate the whole catalog, badge affected plugins, notify authors. This single feature is most of the "ecosystem keeps working while Luna evolves" story.
- **Channels** — `stable` / `beta` / `nightly` per plugin; agents subscribe to a channel.
- **Curation workflow** — for company marketplaces: a publisher submits, a reviewer approves, then it's visible to agents. Enterprise marketplaces are *curated allowlists*, not open bazaars.

### 6.2 What the agent-side experience looks like

- `/marketplace add <url>` → Luna fetches identity doc, shows the marketplace's name+key fingerprint, **owner approves** (this is an approval-gated action, kind `marketplace.add` — fits Luna's existing approval architecture exactly).
- "Luna, I need to send invoices" → Luna searches its marketplaces, finds `acme-internal/invoicing`, presents the plugin card (permissions, publisher, compat ✓), owner approves install. Install of a plugin is **always gated** — it's literally "load new code into the trust boundary."
- Updates: Luna can notify ("3 plugin updates available, 1 fixes a security advisory") — applying them is gated; org policy can auto-approve patch-level updates from exclusive marketplaces.

### 6.3 Open question — packaging format

Options: (a) plain zip/tarball of the plugin folder (matches Luna's "zip the folder, drop in plugins/" philosophy); (b) Python wheel (pip ecosystem, but drags in pip's dependency hell and makes non-Python assets awkward); (c) OCI artifact (registry infra for free, content-addressing for free, but heavyweight and unfamiliar to plugin authors). **Leaning (a) with a manifest + hash envelope** — simplest thing that preserves "a plugin is a folder." Dependencies on PyPI packages declared in the manifest and installed by Luna's loader into per-plugin venvs is its own design problem (flagged for the Luna project, not solved here).

---

## 7. Pricing (designed now, implemented later)

**Decision: no billing code in early phases.** But accounts, orgs, and marketplaces must be modeled so plans can attach later without a migration nightmare. Concretely: every org carries a `plan` field from day one (everyone on `free`), feature checks go through one `org_can(org, feature)` gate (all features return true for now), and usage events (publishes, downloads, active agents pulling from a marketplace) are **recorded from day one** — metering data is cheap to capture and impossible to reconstruct.

### 7.1 What's free forever (protocol promise)

- The protocol spec, the static builder (`luna-mp build`), self-hosting your own marketplace on your own infra.
- Reading/installing from any public marketplace.
- This mirrors Luna's "open platform" stance: nobody is forced through our service to participate in the ecosystem.

### 7.2 Plausible paid axes (pick later, design for all)

| Axis | Free tier | Paid |
|---|---|---|
| **Privacy** | Public marketplaces | Private marketplaces (tokens, SSO) — *the* vendor/enterprise feature, probably the primary revenue line |
| **Seats & roles** | 1–2 members | Teams, reviewer roles, curation workflow |
| **Marketplaces per org** | 1 | Many (vendors running one per client) |
| **Compute** | Basic validation | Full conformance matrix runs, security scans, compat watch with author notifications |
| **Identity** | `{slug}.marketplaces.com.ai` | Custom domains, verified-publisher badge |
| **Enterprise** | — | SSO/SAML, audit log export, SLA, dedicated infra, on-prem service license |
| **Distribution add-ons** | Self-host everything | Our CDN for artifacts behind a self-hosted index (hybrid) |

### 7.3 The payments question (explicitly deferred)

Luna already has `license: Commercial` + `requires_entitlement` in plugin manifests. The marketplace *could* eventually become the entitlement issuer and payment rail (take-rate on paid plugins, like app stores). That is a whole product — billing, refunds, tax, fraud, publisher payouts. **Deferred past M4.** What we do now: keep entitlement fields in the published manifest schema, and make sure nothing in the protocol assumes plugins are free — so the rail can be added without a protocol break.

### 7.4 Pricing principles

- Never charge for *trust-critical* features. Signing, key pinning, transparency log presence — these are free on every tier, or the cheap tiers become the insecure tiers and the whole ecosystem's reputation pays for it.
- Charge operators (companies, vendors), not agent owners. The person adding a marketplace to their Luna should never hit a paywall we control.
- Self-hosters are first-class protocol citizens, not a leaky bucket to plug — they validate the openness claim and feed the directory/verification business (§8.2).

---

## 8. Security

Per the trust model (§3): trust is established by *choosing* a marketplace operator, like choosing a vendor. Our security work is making sure that **once trust is given, the channel can't betray it** — the plugin that arrives is exactly what the trusted operator published. Four distinct attack surfaces:

### 8.1 Tampered supply chain (poisoning a trusted marketplace's plugins)

- **Publisher signing.** Authors sign artifacts with their key (registered to their account, ideally backed by Sigstore-style keyless signing later). The marketplace **countersigns** after its checks pass. Agents verify both.
- **Immutability + transparency log.** Published versions are append-only; the service maintains a public transparency log (Merkle tree, à la certificate transparency / sigstore Rekor) of every (marketplace, plugin, version, hash). A compromised marketplace that serves two different "1.4.2"s to different victims becomes *detectable*.
- **Permissions-diff on update.** An update that adds new gated tools, new egress hosts, or new vault access gets a louder approval card: "v2.0 newly requests: egress to evil.com." Most real-world supply-chain attacks are *updates* to trusted packages — this protects the operator's curation promise even when an upstream author's account is compromised.

### 8.2 Hijacked marketplace link

Scenario: agent config points at `https://plugins.acme.com`; DNS/server is compromised; attacker serves a poisoned index.

- **Key pinning at add time (TOFU + approval).** When the owner adds a marketplace, Luna pins its signing key. Every future fetch must verify against the pinned key. A hijacker without the private key can serve nothing installable. Key rotation requires either a signature chain from the old key or a re-approval by the owner.
- **TUF-style roles for the index** (adopt the ideas, not necessarily the full spec): a short-lived signed *timestamp* file defeats **freeze attacks** (serving a stale index to hide a security fix); snapshot signing defeats **mix-and-match** (serving old plugin A with new plugin B); rollback protection (version counters) defeats downgrade attacks.
- **The directory service** — this is where `marketplaces.com.ai` earns strategic value beyond hosting: it can act as a **verification directory** for *any* marketplace, including self-hosted ones. A marketplace registers `(id, url, key)` in the directory; Luna cross-checks pinned keys against the directory and the transparency log. Hijacking then requires compromising both the marketplace AND the directory. (Open question: does this make the directory a centralization point the open protocol shouldn't depend on? Probably: directory = recommended default, protocol works without it.)

### 8.3 Malicious marketplace (the operator is the attacker)

First line of defense is the trust model itself: **don't add marketplaces from operators you don't trust** — same rule as Luna's vendor trust. The protocol's job is capping the blast radius of a mistake:

- Namespacing + no-cross-marketplace-updates (§5.4): a malicious marketplace you added can only poison plugins *installed from it*, never shadow or "update" your other plugins.
- Tier policy: marketplaces can never deliver `bonded` plugins, and `system`/provider plugins (memory, vault) only install from marketplaces the owner has explicitly marked as *vetted* — a higher trust grade than merely *added*.
- Exclusive mode (§5.4) inverts this for enterprises: the org's own marketplace is the only one, so "malicious marketplace" reduces to "compromised insider," which is curation/review territory.

### 8.4 Impersonation (typosquatting, lookalike marketplaces)

- `marketplaces.com.ai` subdomains are issued by us with org verification (domain proof for custom names, manual review for brand names — the "verified publisher" checkmark pattern).
- The catalog UI shows publisher identity prominently; bare-name installs warn when a name closely matches a plugin in a higher-priority marketplace (edit-distance check — boring, effective).
- Plugin namespace squatting policy from day one (reserve `luna-*`, `official-*`; dispute process). Cheap now, painful later.

### 8.5 What we deliberately do NOT promise

Runtime sandboxing of marketplace plugins. Luna's model is trust-at-install, and pretending the marketplace adds a runtime sandbox would be security theater. The honest claim: **the marketplace makes the install decision well-informed and the supply chain tamper-evident.** (If Luna ever adds plugin sandboxing tiers, the manifest already carries the permission declarations a sandbox would enforce — we're forward-compatible with that future, we just don't claim it.)

---

## 9. Phasing (strawman)

Luna-side prerequisites are tracked in [`luna-change-requests.md`](./luna-change-requests.md); phases below are **this project's** deliverables, with their Luna dependencies noted.

| Phase | Deliverable | Depends on Luna |
|---|---|---|
| **M1** | Protocol spec v0 + static marketplace builder (`luna-mp build`); one decoupled plugin installed into a real agent from a static marketplace, passing dojo | CR-1 (SDK), CR-3 (client), CR-4 (loader) — at least in prototype form |
| **M2** | Service MVP: accounts, orgs (with `plan` field + usage metering from day one), one marketplace per org, publish CLI, signed index, catalog UI, private marketplaces with tokens | — |
| **M3** | Compat watch + publish-time conformance runs + compatibility matrix in catalog | CR-2 (capability manifests), CR-6 (conformance suite) |
| **M4** | Transparency log, directory service, verified publishers, channels, curation workflow | — |
| **M5+** | Pricing enforcement (§7), paid-plugin rail (§7.3) | — |

M1 is the moment of truth and is deliberately *before* building any service: a static folder of signed files, one real plugin, one real agent installing it.

---

## 10. Open Questions (for discussion)

1. **Knowhow packs and skills** — are they marketplace artifacts too? They fit the same envelope (versioned, signed folders) and might be the *easiest* thing to distribute since they carry no code. Possibly the real M1 candidate.
2. **The directory's centralization tension** (§8.2) — open protocol with an optional trust directory we operate: where exactly is the line so self-hosters aren't second-class?
3. **MCP overlap** — Luna already gains tools via MCP servers. When should something be a marketplace plugin vs. an MCP server an agent connects to? Rough answer: plugins integrate deeply (prompt, UI, DB, events); MCP is tools-only. The vision should say this crisply somewhere.
4. **Who hosts artifacts for self-hosted marketplaces** — fully self-hosted, or self-hosted index + our CDN for artifacts (the §7.2 hybrid revenue line)?
5. **Marketplace-of-marketplaces UX** — should an agent owner be able to add `marketplaces.com.ai` itself and discover marketplaces from within Luna?
6. **Naming** — "marketplace" per org vs. "registry"? (npm/cargo say registry; app stores say marketplace; we're closer to the latter because curation is first-class.)

---

## 11. Principles to Hold Onto

- **The protocol must work as static files.** If it ever requires our compute, it stopped being open.
- **Trust is vendor-shaped.** Adding a marketplace = trusting its operator. We transmit trust tamper-proofly; we don't manufacture it.
- **Installs are approvals.** Loading code into the trust boundary is the most consequential action a Luna agent can take; it uses the same gate architecture as everything else in Luna.
- **Names are qualified, updates are sticky.** Dependency confusion is the attack we refuse to inherit from npm/PyPI.
- **Compatibility is computed, not promised.** Capability manifests + conformance runs, not changelog prose.
- **Decoupling is Luna's job; readiness is ours.** We spec what we need, they evolve the core; the service works even while most plugins are still in-tree.
- **Local plugins stay first-class.** The marketplace adds an install source; it never becomes a gatekeeper for the local folder, Luna's self-written plugins, or coupled in-tree plugins.
- **Pricing is designed in, switched on later.** Plans, feature gates, and metering exist structurally from day one; no billing code until the ecosystem justifies it.
