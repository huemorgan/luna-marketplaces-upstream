#!/usr/bin/env python3
"""Package a plugin into a deterministic zip with a single top-level package dir.

  python scripts/package_plugin.py plugins/my-plugin
  python scripts/package_plugin.py plugins/my-plugin -o dist/

The plugin dir must contain `luna-plugin.toml` (read for name+version) and the entry package.
Produces `<name>-<version>.zip` whose single top-level dir is the `entry` package.

See docs/CREATING-A-PLUGIN.md / docs/UPDATING-A-PLUGIN.md.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def _find_manifest(plugin_dir: Path) -> Path:
    direct = plugin_dir / "luna-plugin.toml"
    if direct.exists():
        return direct
    matches = list(plugin_dir.rglob("luna-plugin.toml"))
    if not matches:
        print(f"! no luna-plugin.toml under {plugin_dir}", file=sys.stderr)
        raise SystemExit(2)
    return matches[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Zip a Luna plugin (single top-level dir).")
    ap.add_argument("plugin_dir", help="path to the plugin directory")
    ap.add_argument("-o", "--out", default=".", help="output directory (default: .)")
    args = ap.parse_args()

    plugin_dir = Path(args.plugin_dir).resolve()
    if not plugin_dir.is_dir():
        print(f"! not a directory: {plugin_dir}", file=sys.stderr)
        return 2

    manifest_path = _find_manifest(plugin_dir)
    manifest = tomllib.loads(manifest_path.read_text())
    name = manifest["name"]
    version = manifest["version"]
    entry = manifest.get("entry", name.replace("-", "_"))

    # The package dir = the dir that contains the manifest (the `entry` package).
    pkg_dir = manifest_path.parent
    if pkg_dir.name != entry:
        print(f"  note: entry='{entry}' but package dir is '{pkg_dir.name}'", file=sys.stderr)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_zip = out_dir / f"{name}-{version}.zip"

    files = sorted(
        p for p in pkg_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            arcname = Path(entry) / f.relative_to(pkg_dir)
            z.write(f, arcname.as_posix())

    print(f"✓ {out_zip}  ({len(files)} files, top-level dir: {entry}/)")
    print(f"  publish:  scripts/publish_plugin.sh {out_zip.name} <marketplace-slug>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
