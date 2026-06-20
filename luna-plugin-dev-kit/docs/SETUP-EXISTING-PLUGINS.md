# Setting Up the Existing Plugins (workspace bootstrap)

> Goal: one Cursor window where you can read and build alongside **every plugin that already
> exists** in the official marketplace — without 100 separate projects, and without git
> submodules.

The model is a **multi-root workspace**: each plugin is an independent folder; one
`.code-workspace` file opens them all together. See `PLUGIN-ARCHITECTURE.md` for why each
plugin stays its own repo.

---

## Quick start

From the kit root:

```bash
# 1) Pull every existing plugin's source into ./plugins/
python scripts/sync_plugins.py

# 2) Open the multi-root workspace in Cursor
cursor luna-plugins.code-workspace      # or: File → Open Workspace from File…
```

You now have one window with the kit docs, the template, and every existing plugin.

---

## What `sync_plugins.py` does

It reads the live catalog and materializes each plugin locally:

1. `GET https://marketplaces.com.ai/mp/official/index.json` — the authoritative list of
   existing plugins.
2. For each plugin, downloads `…/plugins/{name}/{version}/artifact.zip`.
3. Unzips it into `plugins/<name>/` (the zip's single top-level dir).

This always works against what's actually published right now. The result is the *source* of
each plugin, ready to read, copy patterns from, or fork.

### Canonical source = GitHub

The marketplace hosts the built artifact; the **source of truth** for each plugin is its
public repo at `github.com/huemorgan/<plugin-name>`. If you intend to *edit and re-publish* a
plugin (not just read it), clone its repo instead so you have history and can push:

```bash
gh repo clone huemorgan/plugin-render plugins/plugin-render
```

`sync_plugins.py --from-github` prefers a `gh repo clone` per plugin and falls back to the
marketplace artifact when a repo doesn't exist yet.

---

## Recommended layout

```
luna-plugin-dev-kit/
  luna-plugins.code-workspace   ← open this
  docs/                         ← these guides
  template/                     ← scaffold for new plugins
  scripts/                      ← sync / package / publish
  plugins/                      ← created by sync_plugins.py
    hello-world/
    hello-world-2/
    plugin-render/
    plugin-files/
    ...
```

The `.code-workspace` includes `plugins/*`, `template/`, and `docs/` as roots, so search,
file tree, and the agent see everything at once. Adding a plugin later = it shows up after a
re-sync; removing one = delete its folder. No submodule pointers to babysit.

---

## After setup

- Building something new? → `CREATING-A-PLUGIN.md`
- Changing an existing plugin? → `UPDATING-A-PLUGIN.md`
- Need the big picture? → `PLUGIN-ARCHITECTURE.md`
