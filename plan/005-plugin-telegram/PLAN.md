# 005 — Publish plugin-telegram

**Produces version:** none

## Context

`plugin-telegram` v0.2.0 adds the official Telegram Bot API channel, including
hosted self-provisioning through luna-service. It must be available from the
official marketplace before a hosted Luna can install and connect it.

Published marketplace versions are immutable. The source artifact must exactly
match the tested and tagged `huemorgan/plugin-telegram` v0.2.0 release.

## Architecture impact

None — this uses the existing first-party `marketplace-src/<plugin>/` seeding and
immutable artifact publication path.

## Goals

1. Add the tested v0.2.0 plugin source under `marketplace-src/plugin_telegram/`.
2. Preserve the standalone source URL and matching manifest/runtime versions.
3. Deploy the marketplace service so the official catalog publishes the new
   immutable artifact.
4. Verify the official index, detail endpoint, download, and installation into a
   real hosted Luna.

## Non-goals

- Forking or changing plugin behavior inside the marketplace repository.
- Re-publishing different bytes under v0.2.0.
- Adding Telegram to a default bundle before live channel verification passes.

## Approach

1. Copy only package/runtime files from the tagged plugin repository; exclude
   tests, plans, caches, virtual environments, and git metadata.
2. Run marketplace packaging/seed tests and compare manifest/runtime versions.
3. Commit and push the focused marketplace branch.
4. Deploy `luna-marketplaces`, verify
   `https://marketplaces.com.ai/mp/official/index.json`, and install through the
   real Luna marketplace UI.

## Risks

- Source drift between standalone and seeded copies: compare all copied files and
  record the source commit/tag.
- Immutable-version collision: verify v0.2.0 is absent before deployment; never
  overwrite an existing version with different bytes.
- Private GitHub visibility: the official artifact is self-contained and does
  not require marketplace runtime access to the source repository.

## Acceptance criteria

- [ ] `plugin-telegram` v0.2.0 appears in the official catalog.
- [ ] Artifact downloads with a valid SHA-256 and includes one top-level
      `plugin_telegram/` package.
- [ ] Manifest, package, and runtime versions agree.
- [ ] A hosted Luna installs it from the official marketplace.
- [ ] Plugin settings render and begin the BotFather connection flow.

## Verification

```bash
cd service && uv run pytest -q
curl -fsS https://marketplaces.com.ai/mp/official/index.json
```

Then install `plugin-telegram` in a real Luna through the browser, open its
settings page, and verify no token or secret is exposed in the DOM or network
responses after connection.
