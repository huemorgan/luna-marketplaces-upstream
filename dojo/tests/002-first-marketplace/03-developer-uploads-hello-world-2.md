# 03 — A developer uploads hello-world-2 through the service

**Goal:** prove the runtime upload path — no repo commit, no redeploy — and that
the uploaded plugin is immediately served to Luna.

## Preconditions
- `examples/hello_world_2/` packaged into a zip (one top-level dir
  `hello_world_2/` with `__init__.py` + `luna-plugin.toml`).

## Steps (real browser, management SPA at `/app`)
1. Open `https://luna-marketplaces.onrender.com/app`. Sign up a new account.
2. Create an org, then create a marketplace (e.g. slug `dev-plugins`).
3. Open the marketplace → **Add Plugin** tab → choose the `hello-world-2.zip`
   → click **Upload**.
4. Confirm the success alert, then see `hello-world-2` in the marketplace's
   Plugins list.
5. In a new tab, open `https://luna-marketplaces.onrender.com/mp/dev-plugins/index.json`.

## Expected
- Upload succeeds reading the manifest from inside the zip (no manifest paste).
- `hello-world-2` appears in the SPA Plugins list and in `/mp/dev-plugins/index.json`
  with a `sha256` equal to the uploaded zip's hash.
- Downloading the artifact and re-hashing matches the index.

## Pass/Fail
- PASS: upload works and the plugin is served with a matching hash.
- FAIL: upload errors, manifest not read, or plugin missing from the index.

## Evidence
Screenshots: upload form, success state, Plugins list, served index.json.
