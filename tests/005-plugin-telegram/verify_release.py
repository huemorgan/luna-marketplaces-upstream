"""Verify the local marketplace copy of plugin-telegram v0.2.0."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "service"
SOURCE = REPO.parent / "plugin-telegram"
TARGET = REPO / "marketplace-src" / "plugin_telegram"
TAG = "v0.2.0"
COMMIT = "f7e8a0bac5a795c2829ade92fb8bbe31eaed2ceb"
VERSION = "0.2.0"
ARTIFACT_SHA256 = "1b79d35898a60fa428d0610e54638a1f46a0a9f71bcf0c8e239c9dfe944f7f42"

sys.path.insert(0, str(SERVICE))


def git(*args: str, text: bool = False) -> bytes | str:
    return subprocess.check_output(
        ["git", "-C", str(SOURCE), *args],
        text=text,
    )


def verify_source_and_artifact() -> tuple[bytes, dict, list[str]]:
    commit = str(git("rev-parse", f"{TAG}^{{}}", text=True)).strip()
    assert commit == COMMIT, commit

    raw_names = git(
        "ls-tree",
        "-r",
        "--name-only",
        "-z",
        TAG,
        "--",
        "plugin_telegram",
    )
    assert isinstance(raw_names, bytes)
    names = [name.decode() for name in raw_names.split(b"\0") if name]
    expected_rel = [
        Path(name).relative_to("plugin_telegram").as_posix() for name in names
    ]
    actual_rel = sorted(
        path.relative_to(TARGET).as_posix()
        for path in TARGET.rglob("*")
        if path.is_file()
    )
    assert actual_rel == sorted(expected_rel), (actual_rel, expected_rel)
    for name in names:
        tagged = git("show", f"{TAG}:{name}")
        assert isinstance(tagged, bytes)
        copied = (REPO / "marketplace-src" / name).read_bytes()
        assert copied == tagged, name

    manifest = tomllib.loads((TARGET / "luna-plugin.toml").read_text())
    init_text = (TARGET / "__init__.py").read_text()
    routes_text = (TARGET / "routes.py").read_text()
    project_raw = git("show", f"{TAG}:pyproject.toml", text=True)
    assert isinstance(project_raw, str)
    source_project = tomllib.loads(project_raw)
    package_match = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)',
        init_text,
        re.MULTILINE,
    )
    assert package_match is not None
    package_version = package_match.group(1)
    assert manifest["version"] == VERSION
    assert package_version == VERSION
    assert source_project["project"]["version"] == VERSION
    assert "version=__version__" in init_text
    assert 'result["version"] = "0.2.0"' in routes_text
    assert '_SETTINGS_HTML.replace("__TG_VERSION__", "0.2.0")' in routes_text

    from app.packaging import package_source, read_manifest_from_zip

    first, artifact_sha, packaged_manifest = package_source(TARGET)
    second, artifact_sha_2, _ = package_source(TARGET)
    assert first == second
    assert artifact_sha == artifact_sha_2 == ARTIFACT_SHA256
    parsed_manifest, top = read_manifest_from_zip(first)
    assert top == "plugin_telegram"
    assert parsed_manifest == packaged_manifest == manifest

    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        archive_names = archive.namelist()
        assert archive_names == [
            f"plugin_telegram/{name}" for name in sorted(expected_rel)
        ]
        forbidden_parts = {
            ".git",
            ".venv",
            "__pycache__",
            "tests",
            "test",
            "plans",
            "plan",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        }
        assert not any(
            forbidden_parts.intersection(Path(name).parts)
            or name.endswith((".pyc", ".pyo", ".env"))
            for name in archive_names
        )
        payload = b"\n".join(archive.read(name) for name in archive_names)
        secret_patterns = {
            "telegram_bot_token": (
                rb"(?<![A-Za-z0-9])\d{8,12}:[A-Za-z0-9_-]{30,}"
                rb"(?![A-Za-z0-9])"
            ),
            "private_key": (
                rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
            ),
            "aws_access_key": rb"AKIA[0-9A-Z]{16}",
        }
        matches = {
            label: pattern
            for label, pattern in secret_patterns.items()
            if re.search(pattern, payload)
        }
        assert not matches, matches

    print(f"source_commit={commit}")
    print(
        f"tagged_files={len(names)} copied_files={len(actual_rel)} "
        "byte_identical=yes"
    )
    print(
        f"versions: source_project={source_project['project']['version']} "
        f"manifest={manifest['version']} package={package_version} "
        f"runtime={VERSION}"
    )
    print(f"artifact_sha256={artifact_sha}")
    print(f"artifact_bytes={len(first)} deterministic=yes")
    print(f"artifact_top_level={top} archive_files={len(archive_names)}")
    print("artifact_hygiene=no secrets/caches/tests/plans/git metadata")
    return first, manifest, archive_names


async def verify_seed(expected_artifact: bytes) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.database import init_db
    from app.main import app
    from app.seed_core import seed_core_plugins

    await init_db()
    first = await seed_core_plugins()
    telegram_log = [line for line in first if "plugin-telegram" in line]
    assert telegram_log == [
        "seeded plugin-telegram 0.2.0 sha256=1b79d35898a6"
    ], telegram_log

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/mp/official/index.json")
        assert response.status_code == 200
        matches = [
            entry
            for entry in response.json()["plugins"]
            if entry["name"] == "plugin-telegram"
        ]
        assert len(matches) == 1
        entry = matches[0]
        assert entry["version"] == VERSION
        assert entry["sha256"] == ARTIFACT_SHA256
        artifact = await client.get(f"/mp/official/{entry['artifact']}")
        assert artifact.status_code == 200
        assert artifact.content == expected_artifact
        assert hashlib.sha256(artifact.content).hexdigest() == entry["sha256"]

    second = await seed_core_plugins()
    telegram_second = [line for line in second if "plugin-telegram" in line]
    assert telegram_second == [
        "ok plugin-telegram 0.2.0 (unchanged)"
    ], telegram_second
    print(telegram_log[0])
    print(f"index_version={entry['version']} sha256={entry['sha256']}")
    print(f"artifact_bytes={len(artifact.content)} hash_match=yes")
    print(telegram_second[0])


def main() -> None:
    artifact, _manifest, _archive_names = verify_source_and_artifact()
    with tempfile.TemporaryDirectory(prefix="luna-mp-telegram-seed-") as tmp:
        root = Path(tmp)
        os.environ["DATABASE_URL"] = (
            f"sqlite+aiosqlite:///{root / 'test.db'}"
        )
        os.environ["ARTIFACTS_DIR"] = str(root / "artifacts")
        os.environ["MARKETPLACE_SRC"] = str(REPO / "marketplace-src")
        os.environ["JWT_SECRET"] = "test-secret"
        asyncio.run(verify_seed(artifact))
    print("LOCAL RELEASE VERIFICATION PASS")


if __name__ == "__main__":
    main()
