# Phase 001 — Protocol Spec & Reference Tooling

> The marketplace format becomes real: a precise open spec, JSON schemas, signed test vectors, and a reference CLI (`luna-mp`) that builds and verifies static marketplaces. Zero dependency on the Luna project — this phase is entirely ours.

**Exit criterion (one sentence):** a third party could implement a compatible marketplace from the spec alone, and `luna-mp verify` catches every tamper class we claim to defend against.

---

## 1. Scope

### In scope
- Protocol spec v0 documents + JSON Schemas
- Signing design (keys, document signatures, freshness, rollback protection)
- Packaging format for plugin artifacts
- `luna-mp` CLI: `keygen`, `build`, `verify`, `serve`
- Test vectors: golden valid fixtures + tampered fixtures per attack class
- Sample marketplace (two dummy plugins) built and verified in CI

### Out of scope (explicitly)
- Any hosted service code (phase 003)
- Any Luna-side integration (phase 002)
- `search` endpoint (optional protocol extension; spec reserves it, doesn't define it)
- Payments/entitlement fields beyond carrying them opaquely in manifests
- Key *rotation* flows (spec reserves the `previous_keys` field; full flow is phase 006)

---

## 2. Deliverable 1 — The Spec (`spec/` at repo root)

The spec is a public artifact — written to be read by implementers outside this company. Files:

| File | Contents |
|---|---|
| `spec/00-overview.md` | Concepts, actors, trust model summary, conformance levels (what MUST a minimal static marketplace serve) |
| `spec/01-identity.md` | `/.well-known/luna-marketplace.json`: marketplace id (UUIDv7), display name, protocol version, signing keys, endpoints, auth hints for private marketplaces |
| `spec/02-index.md` | `index.json` (the signed catalog summary), `plugins/{name}/versions.json`, snapshot + timestamp documents, freshness window, version counters (rollback protection) |
| `spec/03-manifest.md` | The published plugin manifest: identity (`namespace/name`), semver, license + entitlement passthrough, `[compat]` (SDK range + required capabilities), `[provenance]` (source URL, publisher key), permissions summary (tools + policies, egress hosts, provider/vault usage) |
| `spec/04-packaging.md` | Artifact = zip of the plugin folder + detached envelope: sha256, publisher signature, marketplace countersignature. Content-addressed storage layout |
| `spec/05-signing.md` | Key type (Ed25519), canonical JSON serialization (JCS, RFC 8785), signature envelope format, what each role signs, verification algorithm step-by-step |
| `spec/06-naming.md` | Namespace rules, fully-qualified names (`marketplace-id/plugin-name`), reserved prefixes, the sticky-update rule, hierarchy resolution rules for clients |
| `spec/07-client-requirements.md` | Normative MUSTs for installers (key pinning, verify-every-fetch, compat gate, lockfile fields) — this becomes the contract CR-3 implements |

Each document gets a JSON Schema in `spec/schemas/*.schema.json`. The schema **is** the normative shape; prose explains intent.

### Design decisions to settle while writing (with current leanings)

| Decision | Leaning | Why |
|---|---|---|
| Signature envelope | DSSE (the sigstore envelope) over raw detached sigs | Existing tooling, payload-type binding prevents cross-document signature replay |
| Canonicalization | RFC 8785 JCS | Boring, implemented everywhere |
| TUF adoption | TUF *ideas* (timestamp/snapshot/targets separation), not the full spec | Full TUF delegation machinery is overkill for v0; keep the role names so a future migration is sane |
| Timestamp freshness window | 7 days default, marketplace-configurable, client warns at half-life | Static hosts need slack; freeze attacks need a bound |
| Artifact format | zip (not tar) | Windows-friendly, random access, "a plugin is a folder" preserved |
| Index scale | Single `index.json` to ~1k plugins; sharding reserved for v1 | Don't design pagination nobody needs yet |

Settled decisions get recorded in `spec/DECISIONS.md` (mini-ADRs, a paragraph each).

---

## 3. Deliverable 2 — `luna-mp` Reference CLI

Python 3.12, same ecosystem as Luna. Lives in this repo (`tools/luna-mp/`), published to PyPI later (not this phase). Library-first: `luna_mp` package with a thin CLI over it, so the phase-003 service reuses the same build/verify code.

### Commands

```
luna-mp keygen --out keys/                    # Ed25519 keypair for a marketplace or publisher
luna-mp build SRC_DIR -o OUT_DIR \
        --marketplace-key keys/mp.key         # folder of plugin folders → complete static marketplace
luna-mp verify TARGET                          # dir path or https URL → full integrity audit
luna-mp serve OUT_DIR --port 8480              # static dev server (stdlib http.server wrapper)
```

- `build`: validates each plugin's manifest against the schema, zips artifacts, computes hashes, writes versions files, snapshot, timestamp, index, identity doc; signs everything. Re-running on an existing output dir is **append-only** — refuses to overwrite a published version (the immutability rule, enforced in tooling from day zero).
- `verify`: checks every signature, every hash, freshness, version-counter monotonicity vs. a previous state file, schema validity. Output: human-readable report + `--json` for CI. Exit non-zero on any failure.
- Publisher signing: `build` accepts pre-signed artifacts (publisher signed elsewhere) or `--publisher-key` for the solo-operator case where one party is both.

### Repo layout after this phase

```
luna-marketplaces/
  vision/                  # exists
  plan/                    # exists
  spec/                    # NEW — the open spec + schemas + DECISIONS.md
  tools/luna-mp/           # NEW — reference implementation
    luna_mp/               #   library (build, verify, sign, schemas loading)
    tests/
    pyproject.toml
  fixtures/                # NEW — test vectors (see below)
  luna/                    # submodule (reference only this phase)
```

---

## 4. Deliverable 3 — Test Vectors & Tamper Suite

`fixtures/` contains a golden sample marketplace (two dummy plugins: `demo/hello-tool` with one tool, `demo/hello-knowhow` with no code) plus **one tampered variant per attack class**. The tamper suite is the spec's security claims made executable:

| Fixture | Attack class | `verify` must report |
|---|---|---|
| `tampered-artifact/` | Supply-chain: artifact bytes ≠ signed hash | HASH_MISMATCH |
| `wrong-key/` | Hijack: index signed by non-pinned key | KEY_MISMATCH |
| `stale-timestamp/` | Freeze: timestamp older than window | STALE_TIMESTAMP |
| `rolled-back/` | Rollback: version counter decreased | ROLLBACK |
| `mixed-snapshot/` | Mix-and-match: versions file not in snapshot | SNAPSHOT_MISMATCH |
| `mutated-version/` | Immutability: republished existing version with new bytes | VERSION_MUTATION |
| `unsigned-extra/` | Injection: plugin present in dir but absent from signed index | UNLISTED_CONTENT |

pytest runs `verify` across all fixtures in CI (GitHub Actions on this repo — set up as part of this phase). The golden marketplace also round-trips: `build` → `verify` → `serve` → `verify` over HTTP.

---

## 5. Work Order

1. **Skeleton + decisions** — `spec/00`, `DECISIONS.md` entries for the six decisions above. *(the thinking step; everything else is execution)*
2. **Schemas first** — draft all JSON Schemas; dummy documents validating against them.
3. **Signing core** — `luna_mp.sign`: JCS canonicalization, DSSE envelopes, Ed25519 (PyNaCl). Unit tests with fixed keys → deterministic signatures.
4. **`build`** — manifest validation → packaging → metadata generation → signing. Golden fixtures generated by this code, then frozen.
5. **`verify`** — independent re-implementation of the verification algorithm (do not share signing-path code beyond crypto primitives — verify must catch build's bugs).
6. **Tamper suite** — generate the seven tampered fixtures; CI green means all seven rejected + golden accepted.
7. **Prose spec** — write `01`–`07` against the now-working implementation; fix spec/code divergences in whichever is wrong.
8. **`serve` + HTTP round-trip test.**

Steps 3–5 are the bulk. Step 7 deliberately comes late: prose written before working code is fiction.

---

## 6. Acceptance Checklist

- [ ] `luna-mp build` produces a marketplace that `luna-mp verify` passes, from a folder of two dummy plugins
- [ ] All seven tamper fixtures rejected with the correct error class
- [ ] Re-`build` over an existing output refuses to mutate a published version
- [ ] `verify` works identically against a local dir and an HTTP URL
- [ ] Every protocol document validates against its schema; schemas are referenced from the prose spec
- [ ] `spec/07-client-requirements.md` reviewed against `vision/luna-change-requests.md` CR-3 — no contradiction (this file becomes Luna's implementation contract in phase 002)
- [ ] A reader with no context can follow `spec/00-overview.md` → build a toy marketplace by hand (we test this on the Luna agent in phase 002)
- [ ] CI green on the repo

## 7. Risks

| Risk | Mitigation |
|---|---|
| Over-speccing v0 (TUF rabbit hole) | DECISIONS.md leanings above; timebox decision debates — record and move |
| Spec/implementation drift | Prose written last (step 7); schemas + fixtures are the source of truth |
| Crypto subtleties (canonicalization bugs) | JCS + DSSE are established; no homemade constructions; deterministic-signature unit tests |
| Phase 002 reveals protocol gaps | Expected — spec is versioned v0.x precisely so e2e feedback lands as point amendments |
