---
name: devprocess
description: >-
  Numbered feature delivery workflow: plan in plans/NNN-name/PLAN.md, implement,
  add tests in tests/NNN-name/, write execution report. Use when the user says
  $devprocess, devprocess, numbered plan, execution report, or wants a full
  feature slice from spec through verification.
---

# Devprocess — Numbered Feature Delivery

Deliver one feature slice end-to-end: **plan → implement → test → report**.

## When to use

- User invokes `$devprocess`, `devprocess`, or asks for a numbered plan + tests + report
- Starting a new feature that should leave durable artifacts for the next agent/human
- Finishing a feature and need a structured execution report

## Numbering

1. List existing `plans/` folders matching `NNN-*` (three-digit prefix).
2. Pick **next** `NNN` (e.g. if `039-*` exists, use `040`).
3. Use the **same** `NNN` and slug everywhere:
   - `plans/NNN-short-slug/PLAN.md`
   - `tests/NNN-short-slug/` (specs + `report.md`)

Slug: lowercase, hyphenated, short (`ad-visualisation`, not `AdVisualisation`).

**Note:** Plan numbers are independent of DB migration numbers, branch names, or PR numbers.

## Phase 0 — Architecture sync (BEFORE PLAN.md)

`vision/architecture2.md` is the architecture source of truth. Read it
before drafting any plan. The old `plans/AMENDMENTS-AFTER-010.1.md` is
now a redirect — its content lives in architecture2.md.

For every plan, classify each change you intend to make:

| Class | Meaning | What to do |
|---|---|---|
| **ALIGNED** | Plan implements something architecture2 already specifies | Cite the section. Proceed. |
| **ADD** | Plan introduces something architecture2 doesn't cover (new plugin, new contract, new gate, new prompt key, new system app) | Note in PLAN.md under a top-level `## Architecture impact` block: `ADD: <one-line summary> → vision/architecture2.md § <target section>`. After execution, Phase 5 must update architecture2. |
| **CONFLICT** | Plan changes a decision architecture2 already records (substrate swap, gate location, plugin type, schema model, ordering) | **STOP. Do not draft PLAN.md.** Surface the conflict to the user with: (a) the architecture2 section that conflicts, (b) the proposed change, (c) at least two alternatives, (d) ask which to choose. Only resume after the user picks a path; record the chosen path + rationale in PLAN.md and queue the architecture2 update for Phase 5. |

Skip Phase 0 only if the change is a pure bugfix or test-only and touches
nothing architecturally meaningful (no new files in `luna/`, no new plugin
contract, no new event, no schema migration, no prompt-key changes).

## Phase 1 — Plan (`PLAN.md`)

Create `plans/NNN-short-slug/PLAN.md` **before** substantial code changes.

### Required sections

```markdown
# NNN — Human Title

**Produces version:** 0.MM   (or `none` for docs-only plans — see plans/version-strategy.md)

## Context
Why now. What exists today. Pain or gap.

## Architecture impact
For each architectural change in this plan, list one of:
- `ALIGNED: <change> → vision/architecture2.md § <section>` (no arch update needed)
- `ADD: <change> → will add to vision/architecture2.md § <target section>`
- `CONFLICT (resolved): <change> → user chose <path> on <date>; see Decisions below`

If every change is ALIGNED with no ADDs, write "None — fully aligned with current architecture." Skip the section only if Phase 0 marked the work as architecturally insignificant (pure bugfix / test-only).

## Concerns Review
If the project has product/design constraints (e.g. `vision/concerns.md`,
`docs/design-guidelines.md`, `.cursor/rules/*`), read them and list how this
feature satisfies each concern. Skip section only if none exist.

## Goals
Numbered outcomes.

## Non-Goals
Explicit out-of-scope items.

## Approach
Phased steps: schema → API → UI → sync/scripts → verification.
Include file paths when known. Prefer extending existing modules over new abstractions.

## Data / API contract
Schemas, JSON shapes, query params — anything agents and UI must share.

## Risks
Known failure modes and mitigations.

## Acceptance criteria
Checklist of done conditions.

## Verification
Exact commands to run (build, unit tests, e2e). List regression suites if applicable.
```

### Plan quality bar

- **Actionable:** another agent can implement without guessing intent
- **Scoped:** one coherent feature, not a quarter roadmap
- **Honest:** call out demo-only paths, `dispatch_writes`, feature flags, local-only modes
- **Safe migrations:** never drop production data; preserve + verify copies (see project `.cursorrules` if present)

## Phase 2 — Implement

1. Work on a focused branch when the repo uses branches (name ≈ slug).
2. Match project conventions (read surrounding files first).
3. **Minimize scope** — only what the plan requires.
4. If plan assumptions were wrong, **update PLAN.md** with a short "Plan amendments" note rather than silent drift.

### Common layers (adapt to project)

| Layer | Typical artifacts |
|-------|-------------------|
| Schema | `db/migrations/*.sql` — additive, idempotent `IF NOT EXISTS` |
| Server | routes, services, queries |
| Client | pages, components, hooks |
| Tests | see Phase 3 |

## Phase 3 — Tests

Create `tests/NNN-short-slug/` alongside implementation.

### Choose test type

| Type | When |
|------|------|
| **Playwright** (`*.spec.js`) | UI flows, pages, auth, visual behavior |
| **Vitest / Jest** (`*.test.js`) | Query layer, pure functions, API contracts without browser |
| **Both** | Feature touches UI and server logic |

### Playwright conventions (when project has Playwright)

- `testDir: ./tests`, `testMatch: **/*.spec.js`
- Prefer `baseURL` from config; auth via project pattern (e.g. `/api/auth/dev-login` in dev only)
- Add `data-testid` on new interactive UI when tests need stable selectors
- Run: `npx playwright test tests/NNN-short-slug/`

### Server unit tests (when project uses Vitest/Jest)

- Put tests near code (`__tests__/`) or follow repo layout
- Small fixtures; hand-calculable expectations
- Run: project test script (e.g. `npm test --workspace=server`)

### Regression

After adding suite `NNN`, run **prior** related suites if the feature touches shared surfaces (auth, org scope, cohorts, actions tunnel, etc.). Record counts in the report.

## Phase 4 — Execution report

Create `tests/NNN-short-slug/report.md` when implementation is done (pass or blocked).

### Report template

```markdown
# NNN — Human Title — Execution Report

**Branch:** `branch-name` (if applicable)
**Plan:** [`plans/NNN-short-slug/PLAN.md`](../../plans/NNN-short-slug/PLAN.md)
**Tests:** X/Y new · regression summary if run

---

## What was built
Bullets by area (backend, frontend, scripts).

## Schema changes
Migrations, new columns — or "None".

## Files
**New:** list paths
**Modified:** list paths

## Test results
```
paste command output or summary
```

## Issues encountered & resolved
Non-obvious bugs, reverted approaches, env quirks.

## Concerns checklist
Map back to Concerns Review — ✓ or explain gap.

## Remaining / blocked
Only if something failed acceptance criteria.
```

## Phase 4b — Execution summary (`plans/NNN-short-slug/execution-summary.md`)

**Mandatory after every executed plan.** Write `plans/NNN-short-slug/execution-summary.md`
so the planning folder tells the whole story on its own: PLAN.md is the intent,
execution-summary.md is the outcome. `tests/NNN/report.md` stays the raw test evidence;
the summary is the narrative a future planner reads first.

```markdown
# NNN — Human Title — Execution Summary

## What was accomplished
What actually shipped, in plain language. Note anything planned but not delivered.

## What we discovered along the way
Surprises, wrong plan assumptions, non-obvious behaviors of the codebase or
third-party services, dead ends tried and abandoned — the things that cost time
and would cost the next agent time again.

## Things to consider in the future
Follow-ups, deferred work, known risks left in place, upgrade paths, and any
"if we ever touch X again, remember Y" notes.
```

## Phase 5 — Verify & close

Run everything listed under **Verification** in the plan:

```bash
# Typical Funnel Fighters (adjust per project)
npm run build --workspace=client   # if client exists
npm test --workspace=server        # or root npm test
npx playwright test tests/NNN-short-slug/
```

- All acceptance criteria met → report documents pass
- Blocker remains → report documents blocker; do not claim done
- Do **not** commit unless user asks

### Architecture sync (mandatory if Phase 0 found ADD or CONFLICT)

If the plan's `## Architecture impact` section listed any `ADD` or `CONFLICT (resolved)` entries, **before closing**:

1. Open `vision/architecture2.md` and edit the target section(s) to reflect the new reality. Do not just append a banner — change the body so a fresh reader gets the truth.
2. If the change deprecates anything previously stated, mark the deprecated text or delete it; don't leave both versions visible without explanation.
3. Note the architecture update in the execution report under `## Architecture changes` (file paths + one-line summary of what moved).
4. If anything could not be reconciled (e.g. body text that's now wrong but you weren't sure how to phrase the replacement), list it in `## Remaining / blocked` so the next agent picks it up.

A plan that says "ADD" in PLAN.md but ships with `vision/architecture2.md` unchanged is **not** done.

### Version bump (mandatory unless plan is `Produces version: none`)

Per `plans/version-strategy.md` the version on `main` advances when a plan lands.

1. At the **start** of execution, set `luna/__init__.py` `__version__` to the plan's stated produced version with patch reset to `001` — e.g. plan says `Produces version: 0.02` → `__version__ = "0.02.001"`.
2. During execution, every commit bumps the third digit (`0.02.001` → `0.02.002` → …). For multi-commit plans, increment as you go.
3. The execution report records start version → end version under `## Version`.
4. If two plans race for the same MINOR, the second to land bumps to MINOR + 1 and updates its own `Produces version` line in PLAN.md.

A plan with `Produces version: 0.MM` that ships without changing `__version__` is **not** done. Docs-only plans (`Produces version: none`) skip this step.

## Project adapters

Read these when present; fold into Concerns Review and Verification:

| Path | Use |
|------|-----|
| `vision/architecture2.md` | **Architecture source of truth** — read in Phase 0; update in Phase 5 for any ADD/CONFLICT change |
| `vision/concerns.md` | UI terminology, API parity, drilldowns, chart defaults |
| `vision/design_guidelines.md` | Visual system |
| `.cursor/rules/*.mdc` | Time periods (28d not 30d), browser MCP, production DB, caveman tone |
| `architecture/*.md` | Data model source for plans |
| `playwright.config.js` | E2E paths, webServer, baseURL |

### Funnel Fighters specifics

- Monorepo: `server` + `client` workspaces
- E2E: `http://localhost:5173` client, `http://localhost:3000` API
- Dev auth: `GET /api/auth/dev-login` (non-production only)
- Google Ads writes: respect `connection.settings.dispatch_writes`; default local-only
- Monthly UI windows: **28 days** (`28d`), not 30

## Anti-patterns

- Skipping Phase 0 architecture sync and starting PLAN.md cold
- Marking a CONFLICT as ALIGNED to avoid the user-decision step
- Skipping PLAN.md and coding first
- Mismatched `NNN` between `plans/` and `tests/`
- Empty report or report before any verification attempt
- Closing a plan without `plans/NNN-slug/execution-summary.md` (accomplished / discovered / future)
- Destructive migrations without data preservation
- Claiming "done" with failing tests undocumented in report
- Plan ships with `## Architecture impact: ADD` but `vision/architecture2.md` unchanged
- Plan declares `Produces version: 0.MM` but `luna/__init__.py` `__version__` unchanged

## Quick checklist

```
- [ ] Phase 0: vision/architecture2.md read; changes classified ALIGNED/ADD/CONFLICT
- [ ] CONFLICTs surfaced + resolved with user before drafting PLAN.md
- [ ] Next NNN chosen; slug consistent
- [ ] plans/NNN-slug/PLAN.md written (Architecture impact + Concerns Review)
- [ ] PLAN.md `Produces version:` line set (or `none` for docs-only)
- [ ] `luna/__init__.py` `__version__` bumped at start of execution
- [ ] Feature implemented per plan
- [ ] tests/NNN-slug/*.spec.js or *.test.js added
- [ ] Regression suites run if shared code touched
- [ ] tests/NNN-slug/report.md complete with real results
- [ ] plans/NNN-slug/execution-summary.md written (accomplished / discovered / future considerations)
- [ ] vision/architecture2.md updated for every ADD / CONFLICT change
- [ ] Acceptance criteria checked off
```
