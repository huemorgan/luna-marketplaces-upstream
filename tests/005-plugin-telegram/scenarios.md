# 005 — plugin-telegram marketplace scenarios

## Scenario 1 — Official catalog publication

1. Open `https://marketplaces.com.ai/mp/official/index.json`.
2. Locate `plugin-telegram`.
3. Verify version `0.2.0`, non-empty SHA-256, artifact URL, description, and tool
   count match the tagged standalone plugin.

Pass: one non-yanked v0.2.0 entry exists and contains no secrets.

## Scenario 2 — Artifact integrity

1. Download the published artifact.
2. Verify its SHA-256 against the index.
3. Inspect the archive.

Pass: hash matches; archive has one `plugin_telegram/` package; no `.env`, cache,
test fixture, virtual environment, git metadata, BotFather token, or gateway
secret is present.

## Scenario 3 — Hosted Luna install

1. Open a real hosted Luna.
2. Navigate to Marketplace and install Telegram.
3. Open the Telegram plugin settings page.

Pass: installation succeeds without a restart; settings show the hosted
BotFather connection flow and privacy guidance.

## Scenario 4 — Secret-safe connection UI

1. Connect a disposable BotFather bot.
2. Inspect the settings DOM and browser network responses after the POST
   completes.
3. Refresh the page.

Pass: the token field is empty; token and HMAC secret are absent from DOM,
status responses, logs visible to the browser, and subsequent refreshes.
