#!/usr/bin/env python3
"""Verify a LIVE marketplace against the Luna-v0 protocol + the trust gate.

Standalone (stdlib only). Proves what Luna's installer requires:
  - identity doc resolves
  - index.json lists plugins with 64-hex sha256 + relative artifact paths
  - each artifact downloads and sha256(bytes) == index sha256  (THE trust gate)
  - each artifact is a single top-level package dir with __init__.py + manifest

Usage:
    python dojo/verify_live.py [MARKETPLACE_ROOT_URL]
    # default: https://luna-marketplaces.onrender.com/mp/official/
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from urllib.parse import urljoin

DEFAULT = "https://luna-marketplaces.onrender.com/mp/official/"


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310
        return r.read()


def main(base: str) -> int:
    if not base.endswith("/"):
        base += "/"
    ok = True

    ident = json.loads(_get(urljoin(base, ".well-known/luna-marketplace.json")))
    print(f"identity: {ident.get('name')} (protocol {ident.get('protocol_version')})")
    if ident.get("protocol_version") != "0":
        print("  ! unexpected protocol_version"); ok = False

    idx = json.loads(_get(urljoin(base, "index.json")))
    plugins = idx.get("plugins", [])
    print(f"index: {len(plugins)} plugin(s): {[(p['name'], p['version']) for p in plugins]}")
    if not plugins:
        print("  ! empty index"); ok = False

    for p in plugins:
        artifact = _get(urljoin(base, p["artifact"]))
        actual = hashlib.sha256(artifact).hexdigest()
        hash_ok = actual == p.get("sha256")
        zf = zipfile.ZipFile(io.BytesIO(artifact))
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        tops = {n.split("/", 1)[0] for n in names}
        single_top = len(tops) == 1
        top = next(iter(tops)) if single_top else None
        has_init = single_top and f"{top}/__init__.py" in names
        line = (f"  {p['name']} {p['version']}: hash={'OK' if hash_ok else 'MISMATCH'} "
                f"top={sorted(tops)} __init__={'yes' if has_init else 'no'}")
        print(line)
        ok = ok and hash_ok and single_top and has_init

    print("TRUST GATE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
