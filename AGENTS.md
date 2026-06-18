# AGENTS.md — How to work in luna-marketplaces

Operating agreement for any AI agent in this repo. Read it before doing anything.
It folds in the luna project's `.cursor/rules/*` and the `devprocess` skill
(both copied into `.cursor/` here).

---

## 0. The cardinal rule: PLAN BEFORE YOU TOUCH ANYTHING

- **Never start editing code, building, packaging, or running side-effecting
  commands until the user explicitly says go.** ("go", "do it", "execute",
  "apply it", "make the changes".)
- "Make a plan" / "look into X" / "see how Y works" = **read + write a plan
  only**. No source edits.
- Anything non-trivial (3+ steps, new files, new tooling, hosting, deploys)
  gets a numbered plan in `plan/NNN-slug/PLAN.md` **first**, then wait for
  approval.
- When in doubt: ask in plain text, then stop.

Violating this is the #1 way to make the user angry. Do not improvise scope.

## 1. Tone (caveman rule)

- **Answer first.** First sentence is the answer. Context after, only if needed.
- No restating the request. No summarizing what you just did — the diff speaks.
- No hedging, no pleasantries, no "want me to…?" closers.
- Tables / lists / headings welcome when they make it clearer.
- Length matches need: one-line question → one-line answer.
- **Never use multiple-choice popup cards.** All questions and options go as
  plain text in chat. The user hates popup cards.

## 2. Devprocess — numbered feature delivery

Full skill: `.cursor/skills/devprocess/SKILL.md`. The shape:

1. **Number it.** Next `NNN` under `plan/` (this repo uses `plan/`, not
   `plans/`). Same `NNN`+slug for `plan/NNN-slug/PLAN.md` and
   `tests/NNN-slug/`.
2. **Plan** (`PLAN.md`) before code. Required sections: Context, Goals,
   Non-Goals, Approach, Data/API contract, Risks, Acceptance criteria,
   Verification. Be actionable enough that another agent could execute it.
3. **Implement** only after approval. Minimize scope to what the plan says.
   If assumptions were wrong, amend PLAN.md — don't silently drift.
4. **Test** in `tests/NNN-slug/`. For browser/UI flows that means a real
   dojo run (see §4), not just writing test files.
5. **Report** in `tests/NNN-slug/report.md` with real results.
6. **Do not commit unless the user asks.**

Plan thoroughness levels the user may request: `quick`, `medium`, `thorough`.
Default to what they say; if unspecified, `medium`.

## 3. Browser control

- Use the Playwright MCP (`user-playwright`) for any real browser work —
  it drives a real Chrome the user can see.
- Never open browsers you can't control (`open <url>`).
- If you need the user to do a manual browser step (OAuth consent, adding a
  redirect URI, enabling Pages), give exact step-by-step text — don't try to
  automate around it.

## 4. "Dojo test" / "browser test" means ALL of this

1. Write the dojo scenarios (markdown).
2. Start the server.
3. Open a real browser (Playwright MCP).
4. Execute every step yourself — click, navigate, verify with your own eyes.
5. Screenshot as evidence.
6. Don't stop until the feature is visually confirmed end-to-end.
7. If it fails, fix and re-test until green.

Writing the test files alone is NOT running dojo tests.

## 5. Project map

| Path | What |
|---|---|
| `vision/` | Why + what. `vision-draft.md`, `luna-change-requests.md` (CR-1…CR-7). |
| `plan/` | Numbered plans. `ROADMAP.md` is the phase map. |
| `spec/` | The open marketplace protocol spec + JSON schemas. |
| `tools/luna-mp/` | Reference CLI: `keygen`, `build`, `verify`, `serve`. |
| `service/` | The hosted FastAPI service (deployed on Render). |
| `tests/` | Dojo tests + reports, numbered to match plans. |
| `luna/` | Git submodule — the Luna project. Reference; don't edit unless asked. Marketplace integration lives on its `8.5-pluginsdk` branch. |

## 6. Production / hosting

- Service is live on Render: `https://luna-marketplaces.onrender.com`
  (service `srv-d8m7nct8nd3s73dofrm0`, Postgres `luna-mp-db`, Oregon).
- GitHub: `https://github.com/huemorgan2/luna-marketplaces` (account
  `huemorgan2`). The luna submodule is `huemorgan/luna`.
- `.env` / secrets are never committed.

## 7. The integration contract with Luna (v0)

Luna's in-agent client (`plugins/plugin_marketplace`) consumes a **static**
marketplace at a root URL. The non-negotiable format it reads:

| Path | Purpose |
|---|---|
| `/.well-known/luna-marketplace.json` | identity: `{id, name, protocol_version}` |
| `/index.json` | catalog: `{marketplace, plugins:[{name, version, description, sdk_version, artifact, sha256}]}` |
| `/plugins/{name}/{version}/artifact.zip` | the zipped plugin (one top-level package dir) |

The one hard rule: `sha256` in `index.json` MUST equal the hash of the
artifact bytes. Luna refuses to load on mismatch — that's the trust gate.
Reference builder Luna shipped: `luna/fixtures/build_marketplace.py`.

## 8. Anti-patterns (don't)

- Starting to code/build/package before the user says go.
- Skipping the plan and "just doing it."
- Multiple-choice popup cards.
- Opening uncontrollable browsers.
- Committing without being asked.
- Claiming "done" without real verification.
