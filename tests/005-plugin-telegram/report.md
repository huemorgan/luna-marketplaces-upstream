# 005 — Publish plugin-telegram — Local Test Report

**Branch:** `005-plugin-telegram`  
**Plan:** [`plan/005-plugin-telegram/PLAN.md`](../../plan/005-plugin-telegram/PLAN.md)  
**Source:** `plugin-telegram` tag `v0.2.0` at
`f7e8a0bac5a795c2829ade92fb8bbe31eaed2ceb`  
**Artifact SHA-256:**
`1b79d35898a60fa428d0610e54638a1f46a0a9f71bcf0c8e239c9dfe944f7f42`

## Scope

Local package copy, deterministic packaging, isolated seed/registry verification,
and service regression tests only. Commit, push, deploy, production, official
catalog requests, and live browser scenarios were excluded by instruction.

## Files

**New package files:**

- `marketplace-src/plugin_telegram/__init__.py`
- `marketplace-src/plugin_telegram/client.py`
- `marketplace-src/plugin_telegram/context.py`
- `marketplace-src/plugin_telegram/db.py`
- `marketplace-src/plugin_telegram/directives.py`
- `marketplace-src/plugin_telegram/hmac.py`
- `marketplace-src/plugin_telegram/luna-plugin.toml`
- `marketplace-src/plugin_telegram/policy.py`
- `marketplace-src/plugin_telegram/provision.py`
- `marketplace-src/plugin_telegram/routes.py`
- `marketplace-src/plugin_telegram/schemas.py`

**New verification/report files:**

- `tests/005-plugin-telegram/verify_release.py`
- `tests/005-plugin-telegram/report.md`
- `plan/005-plugin-telegram/execution-summary.md`

The pre-existing untracked `PLAN.md` and `scenarios.md` were not modified.

## Commands and results

### Branch and source tag

```text
$ git branch --show-current
005-plugin-telegram

$ git -C "/Users/roy/Library/CloudStorage/GoogleDrive-vaselin@gmail.com/My Drive/my-projects/plugin-telegram" rev-parse 'v0.2.0^{}'
f7e8a0bac5a795c2829ade92fb8bbe31eaed2ceb

$ git -C "/Users/roy/Library/CloudStorage/GoogleDrive-vaselin@gmail.com/My Drive/my-projects/plugin-telegram" status --short
[no output]
```

### Exact package copy

Run from the marketplace repository root:

```text
$ git -C "/Users/roy/Library/CloudStorage/GoogleDrive-vaselin@gmail.com/My Drive/my-projects/plugin-telegram" archive v0.2.0 plugin_telegram | tar -x -C marketplace-src
exit 0
```

### Declared test dependencies

Run from `service/`:

```text
$ uv sync --extra dev
Resolved 50 packages in 4ms
Installed 8 packages in 55ms
exit 0
```

No tracked dependency or lock file changed.

### Reproducible release verification

Run from `service/`:

```text
$ uv run python ../tests/005-plugin-telegram/verify_release.py
source_commit=f7e8a0bac5a795c2829ade92fb8bbe31eaed2ceb
tagged_files=11 copied_files=11 byte_identical=yes
versions: source_project=0.2.0 manifest=0.2.0 package=0.2.0 runtime=0.2.0
artifact_sha256=1b79d35898a60fa428d0610e54638a1f46a0a9f71bcf0c8e239c9dfe944f7f42
artifact_bytes=22549 deterministic=yes
artifact_top_level=plugin_telegram archive_files=11
artifact_hygiene=no secrets/caches/tests/plans/git metadata
seeded plugin-telegram 0.2.0 sha256=1b79d35898a6
index_version=0.2.0 sha256=1b79d35898a60fa428d0610e54638a1f46a0a9f71bcf0c8e239c9dfe944f7f42
artifact_bytes=22549 hash_match=yes
ok plugin-telegram 0.2.0 (unchanged)
LOCAL RELEASE VERIFICATION PASS
exit 0
```

This check compares every copied file directly with its tagged Git blob, checks
all version surfaces, builds the artifact twice, inspects archive paths and secret
patterns, seeds a temporary SQLite marketplace, downloads the artifact through
the local ASGI registry, verifies its hash, and reseeds for idempotency.

### Focused packaging suite

Run from `service/`:

```text
$ uv run pytest -q tests/test_packaging.py
....                                                                     [100%]
4 passed in 0.02s
exit 0
```

### Focused seed/registry suite

Run from `service/`:

```text
$ uv run pytest -q tests/test_registry_e2e.py
....                                                                     [100%]
4 passed in 1.34s
exit 0
```

### Full marketplace service suite

This is the plan's exact local verification command, run from `service/`:

```text
$ uv run pytest -q
................                                                         [100%]
16 passed, 9 warnings in 1.93s
exit 0
```

All nine warnings are the existing `datetime.utcnow()` deprecation at
`service/app/auth.py:65`.

## Issues encountered and resolved

1. A raw source-directory comparison reported ignored source `__pycache__` files.
   The definitive test now compares only the 11 tracked tag files directly against
   Git object bytes.
2. Initial `uv run pytest` attempts returned
   `Failed to spawn: pytest: No such file or directory`. Installing the declared
   `dev` extra with `uv sync --extra dev` resolved this; all reruns passed.
3. The first ad-hoc seed wrapper completed every assertion but used zsh's read-only
   variable name `status`, causing a wrapper exit of 1. The durable Python verifier
   uses `TemporaryDirectory` and exits 0.

## Result

Local acceptance criteria pass. The artifact is deterministic, byte-identical to
the tagged package source, version-consistent, structurally valid, clean, and
successfully seeded through the local marketplace path.

## Remaining / intentionally excluded

- Commit and push.
- Deployment and production access.
- Official catalog/index/download verification.
- Hosted Luna installation and settings rendering.
- Live BotFather connection and browser DOM/network secret inspection.
