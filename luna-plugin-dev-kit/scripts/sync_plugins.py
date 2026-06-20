#!/usr/bin/env python3
"""Pull every existing Luna plugin's source into ./plugins/.

Default: read the live marketplace catalog and unzip each plugin's artifact (works against
whatever is published right now).

  python scripts/sync_plugins.py
  python scripts/sync_plugins.py --slug official
  python scripts/sync_plugins.py --from-github   # prefer `gh repo clone huemorgan/<name>`

See docs/SETUP-EXISTING-PLUGINS.md.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://marketplaces.com.ai"
KIT_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = KIT_ROOT / "plugins"


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310
        return json.load(r)


def _get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
        return r.read()


def _unzip_into(data: bytes, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        # The zip holds a single top-level package dir; extract it to dest.
        tmp = dest.parent / f".{dest.name}.tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        z.extractall(tmp)
        roots = [p for p in tmp.iterdir() if p.is_dir()]
        if len(roots) == 1:
            shutil.move(str(roots[0]), str(dest))
            shutil.rmtree(tmp)
        else:
            shutil.move(str(tmp), str(dest))


def _from_github(name: str, dest: Path) -> bool:
    if shutil.which("gh") is None:
        return False
    if dest.exists():
        shutil.rmtree(dest)
    res = subprocess.run(
        ["gh", "repo", "clone", f"huemorgan/{name}", str(dest)],
        capture_output=True, text=True,
    )
    return res.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync existing Luna plugins locally.")
    ap.add_argument("--slug", default="official", help="marketplace slug (default: official)")
    ap.add_argument("--from-github", action="store_true",
                    help="prefer `gh repo clone huemorgan/<name>`, fall back to artifact")
    args = ap.parse_args()

    root = f"{BASE}/mp/{args.slug}"
    print(f"→ reading catalog: {root}/index.json")
    try:
        index = _get_json(f"{root}/index.json")
    except Exception as e:  # noqa: BLE001
        print(f"  ! failed to read catalog: {e}", file=sys.stderr)
        return 1

    plugins = index.get("plugins", [])
    if not plugins:
        print("  (no plugins published)")
        return 0

    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"→ {len(plugins)} plugin(s) → {PLUGINS_DIR}\n")

    for p in plugins:
        name, version = p["name"], p["version"]
        dest = PLUGINS_DIR / name
        if args.from_github and _from_github(name, dest):
            print(f"  ✓ {name} {version}  (cloned github.com/huemorgan/{name})")
            continue
        try:
            data = _get_bytes(f"{root}/{p['artifact']}")
            _unzip_into(data, dest)
            print(f"  ✓ {name} {version}  ({len(data):,} bytes)  {p.get('description','')[:50]}")
        except Exception as e:  # noqa: BLE001
            print(f"  ! {name} {version}: {e}", file=sys.stderr)

    print("\nDone. Open luna-plugins.code-workspace in Cursor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
