"""Unit tests for deterministic packaging + manifest handling."""

from pathlib import Path

from app.packaging import (
    index_entry_from_manifest,
    package_dir_to_zip,
    package_source,
    read_manifest_from_zip,
    sha256_hex,
)

REPO = Path(__file__).resolve().parents[2]
HELLO = REPO / "marketplace-src" / "hello_world"


def test_packaging_is_deterministic():
    a = package_dir_to_zip(HELLO)
    b = package_dir_to_zip(HELLO)
    assert a == b, "zip bytes must be byte-for-byte stable"
    assert sha256_hex(a) == sha256_hex(b)


def test_package_source_returns_manifest_and_hash():
    zip_bytes, sha256, manifest = package_source(HELLO)
    assert manifest["name"] == "hello-world"
    assert manifest["version"] == "0.1.0"
    assert sha256 == sha256_hex(zip_bytes)


def test_artifact_has_single_top_level_dir_with_manifest_and_init():
    zip_bytes, _, _ = package_source(HELLO)
    manifest, top = read_manifest_from_zip(zip_bytes)
    assert top == "hello_world"
    assert manifest["name"] == "hello-world"


def test_index_entry_shape_matches_luna_v0():
    zip_bytes, sha256, manifest = package_source(HELLO)
    entry = index_entry_from_manifest(manifest, sha256)
    assert set(entry) >= {"name", "version", "description", "sdk_version", "artifact", "sha256"}
    assert entry["artifact"] == "plugins/hello-world/0.1.0/artifact.zip"
    assert entry["sha256"] == sha256
