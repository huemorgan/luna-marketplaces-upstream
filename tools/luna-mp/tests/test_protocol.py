"""Tests for the luna-mp build/verify cycle and tamper detection."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from luna_mp.build import build_marketplace
from luna_mp.signing import KeyPair, canonicalize, hash_bytes, sign_payload
from luna_mp.verify import ErrorCode, verify_marketplace

FIXTURES = Path(__file__).parent.parent.parent.parent / "fixtures"
SOURCE = FIXTURES / "source"


@pytest.fixture
def keys(tmp_path):
    kp = KeyPair.generate()
    kp.save(tmp_path / "keys", "mp")
    return kp


@pytest.fixture
def golden(tmp_path, keys):
    out = tmp_path / "golden"
    build_marketplace(
        source_dir=SOURCE,
        output_dir=out,
        key=keys,
        marketplace_id="test-mp-001",
        marketplace_name="Test Marketplace",
    )
    return out


class TestBuildAndVerify:
    def test_golden_is_valid(self, golden, keys):
        result = verify_marketplace(golden, check_freshness=False)
        assert result.valid
        assert result.plugins_checked == 2
        assert result.versions_checked == 2

    def test_golden_with_pinned_key(self, golden, keys):
        result = verify_marketplace(
            golden, pinned_keys=[keys.public_hex], check_freshness=False
        )
        assert result.valid

    def test_immutability_prevents_overwrite(self, golden, keys):
        """Re-building with changed source for same version must fail."""
        source_copy = golden.parent / "source_mutated"
        shutil.copytree(SOURCE, source_copy)
        manifest_path = source_copy / "hello-tool" / "manifest.json"
        data = json.loads(manifest_path.read_text())
        # Don't change version, but the artifact will differ because we add a file
        (source_copy / "hello-tool" / "extra.txt").write_text("mutation!")

        with pytest.raises(ValueError, match="immutability"):
            build_marketplace(
                source_dir=source_copy,
                output_dir=golden,
                key=keys,
                marketplace_id="test-mp-001",
                marketplace_name="Test Marketplace",
            )


class TestTamperDetection:
    def test_hash_mismatch(self, golden, keys):
        """Tampered artifact bytes should be caught."""
        artifact = golden / "plugins" / "hello-tool" / "1.0.0" / "artifact.zip"
        artifact.write_bytes(b"corrupted content")
        result = verify_marketplace(golden, check_freshness=False)
        assert not result.valid
        assert any(e.code == ErrorCode.HASH_MISMATCH for e in result.errors)

    def test_wrong_key(self, golden, keys):
        """Index signed by non-pinned key should fail."""
        wrong_key = KeyPair.generate()
        result = verify_marketplace(
            golden, pinned_keys=[wrong_key.public_hex], check_freshness=False
        )
        assert not result.valid
        assert any(e.code == ErrorCode.KEY_MISMATCH for e in result.errors)

    def test_stale_timestamp(self, golden, keys):
        """Expired timestamp should be caught."""
        ts_path = golden / "timestamp.json"
        ts_envelope = json.loads(ts_path.read_text())
        # Rewrite with expired timestamp
        expired_payload = {
            "signed_at": int(time.time()) - 86400 * 30,
            "expires_at": int(time.time()) - 86400,
            "version": 1,
        }
        new_envelope = sign_payload(expired_payload, keys.signing_key)
        ts_path.write_text(json.dumps(new_envelope))
        result = verify_marketplace(golden, check_freshness=True)
        assert not result.valid
        assert any(e.code == ErrorCode.STALE_TIMESTAMP for e in result.errors)

    def test_rollback(self, golden, keys):
        """Decreased version counter should be caught."""
        result = verify_marketplace(
            golden,
            previous_snapshot={"version": 999},
            check_freshness=False,
        )
        assert not result.valid
        assert any(e.code == ErrorCode.ROLLBACK for e in result.errors)

    def test_snapshot_mismatch(self, golden, keys):
        """Modified versions file not matching snapshot should be caught."""
        versions_path = golden / "plugins" / "hello-tool" / "versions.json"
        versions_envelope = json.loads(versions_path.read_text())
        payload = versions_envelope["payload"]
        payload["latest"] = "99.99.99"
        new_envelope = sign_payload(payload, keys.signing_key)
        versions_path.write_text(json.dumps(new_envelope))
        result = verify_marketplace(golden, check_freshness=False)
        assert not result.valid
        assert any(e.code == ErrorCode.SNAPSHOT_MISMATCH for e in result.errors)

    def test_unlisted_content(self, golden, keys):
        """Plugin on disk but not in signed index should be caught."""
        rogue_dir = golden / "plugins" / "rogue-plugin"
        rogue_dir.mkdir(parents=True)
        (rogue_dir / "versions.json").write_text("{}")
        result = verify_marketplace(golden, check_freshness=False)
        assert not result.valid
        assert any(e.code == ErrorCode.UNLISTED_CONTENT for e in result.errors)

    def test_version_mutation(self, golden, keys):
        """Rebuilding an existing version with different content triggers immutability."""
        source_copy = golden.parent / "mutated_source"
        shutil.copytree(SOURCE, source_copy)
        (source_copy / "hello-tool" / "mutation.txt").write_text("changed!")

        with pytest.raises(ValueError, match="immutability"):
            build_marketplace(
                source_dir=source_copy,
                output_dir=golden,
                key=keys,
                marketplace_id="test-mp-001",
                marketplace_name="Test Marketplace",
            )
