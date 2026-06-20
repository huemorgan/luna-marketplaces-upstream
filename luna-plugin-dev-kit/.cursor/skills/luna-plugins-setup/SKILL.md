---
name: luna-plugins-setup
description: Sets up a local workspace for Luna plugin development by pulling every existing plugin from the official marketplace into ./plugins/ and opening the multi-root workspace. Use when the user wants to start a Luna plugin project, pull/sync existing plugins, or set up their plugin dev environment.
---

# Set Up the Luna Plugins Workspace

Follow **`../../../docs/SETUP-EXISTING-PLUGINS.md`** (dev-kit root). Summary:

## Steps
1. From the dev-kit root, run **`python scripts/sync_plugins.py`** to pull the source of every
   plugin currently published at `https://marketplaces.com.ai/mp/official/` into `./plugins/`.
   - Use `--from-github` to prefer `gh repo clone huemorgan/<name>` (editable, with history)
     and fall back to the marketplace artifact when a repo doesn't exist yet.
2. Open **`luna-plugins.code-workspace`** in Cursor — a multi-root workspace with `docs/`,
   `template/`, `scripts/`, and `plugins/*` all in one window.
3. Summarize what was pulled (name, version, one-line purpose; leaf vs connector).

## Why multi-root, not submodules
Each plugin stays its own independent repo (required: `github.com/huemorgan/<name>`). A
multi-root workspace gives one window across all of them without submodule pointer-bumping or
detached-HEAD pain. Add a plugin = re-sync; remove one = delete its folder.

## Next
- Build new → **luna-plugin-create** skill.
- Change existing → **luna-plugin-update** skill.
- Understand the model → **luna-plugin-architecture** skill.
