# my-plugin

> A starter Luna plugin. Rename everything from `my-plugin` / `my_plugin` to your own name.

A Luna plugin authored against `luna_sdk` (no `import luna.*`), distributable through a Luna
marketplace.

## Develop

```bash
pip install -e ".[dev]"
pytest
```

Then load it into a local Luna to test agent behavior (see the dev kit's
`docs/CREATING-A-PLUGIN.md`).

## Publish

Bump the version in **both** `my_plugin/luna-plugin.toml` and the `PluginManifest` in
`my_plugin/__init__.py`, then package + upload (see `docs/CREATING-A-PLUGIN.md` and
`docs/UPDATING-A-PLUGIN.md`).

## Structure

```
my_plugin/
  __init__.py        # the LunaPlugin subclass (registers tools)
  luna-plugin.toml   # the data manifest
tests/
  test_my_plugin.py  # unit tests for the tool logic
pyproject.toml
LICENSE
```

## License

MIT — see [LICENSE](LICENSE).
