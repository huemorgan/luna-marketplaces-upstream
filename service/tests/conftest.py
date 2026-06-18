"""Test env setup — must run BEFORE any app module import.

Points the service at a throwaway sqlite DB and temp artifact dir so tests never
touch real data, and at the repo's marketplace-src for seeding.
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="luna-mp-tests-"))
_REPO = Path(__file__).resolve().parents[2]

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'test.db'}"
os.environ["ARTIFACTS_DIR"] = str(_TMP / "artifacts")
os.environ["MARKETPLACE_SRC"] = str(_REPO / "marketplace-src")
os.environ.setdefault("JWT_SECRET", "test-secret")
