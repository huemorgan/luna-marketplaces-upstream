"""Verify a static marketplace for integrity, signatures, and freshness."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .schemas import (
    MarketplaceIdentity,
    MarketplaceIndex,
    PluginVersions,
    Snapshot,
    Timestamp,
)
from .signing import canonicalize, hash_bytes, hash_file, verify_envelope


class ErrorCode(str, Enum):
    HASH_MISMATCH = "HASH_MISMATCH"
    KEY_MISMATCH = "KEY_MISMATCH"
    STALE_TIMESTAMP = "STALE_TIMESTAMP"
    ROLLBACK = "ROLLBACK"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    VERSION_MUTATION = "VERSION_MUTATION"
    UNLISTED_CONTENT = "UNLISTED_CONTENT"
    INVALID_STRUCTURE = "INVALID_STRUCTURE"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"


@dataclass
class VerifyError:
    code: ErrorCode
    message: str
    path: str | None = None


@dataclass
class VerifyResult:
    valid: bool = True
    errors: list[VerifyError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    plugins_checked: int = 0
    versions_checked: int = 0

    def add_error(self, code: ErrorCode, message: str, path: str | None = None):
        self.valid = False
        self.errors.append(VerifyError(code=code, message=message, path=path))

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "plugins_checked": self.plugins_checked,
            "versions_checked": self.versions_checked,
            "errors": [
                {"code": e.code.value, "message": e.message, "path": e.path}
                for e in self.errors
            ],
            "warnings": self.warnings,
        }


def verify_marketplace(
    target: Path,
    pinned_keys: list[str] | None = None,
    previous_snapshot: dict | None = None,
    check_freshness: bool = True,
) -> VerifyResult:
    """Verify a static marketplace directory for integrity.

    target: path to the marketplace root
    pinned_keys: if provided, verify signatures against these keys only
    previous_snapshot: if provided, check rollback protection
    check_freshness: if True, verify timestamp hasn't expired
    """
    result = VerifyResult()

    # Load identity
    identity_path = target / ".well-known" / "luna-marketplace.json"
    if not identity_path.exists():
        result.add_error(
            ErrorCode.INVALID_STRUCTURE,
            "Missing .well-known/luna-marketplace.json",
            str(identity_path),
        )
        return result

    identity_data = json.loads(identity_path.read_text())
    try:
        identity = MarketplaceIdentity(**identity_data)
    except Exception as e:
        result.add_error(
            ErrorCode.INVALID_STRUCTURE,
            f"Invalid identity document: {e}",
            str(identity_path),
        )
        return result

    trusted_keys = pinned_keys or identity.signing_keys

    # Verify timestamp
    timestamp_path = target / "timestamp.json"
    if not timestamp_path.exists():
        result.add_error(
            ErrorCode.INVALID_STRUCTURE, "Missing timestamp.json", str(timestamp_path)
        )
        return result

    timestamp_envelope = json.loads(timestamp_path.read_text())
    try:
        timestamp_payload = verify_envelope(timestamp_envelope, trusted_keys)
    except ValueError as e:
        result.add_error(
            ErrorCode.KEY_MISMATCH, f"Timestamp signature: {e}", "timestamp.json"
        )
        return result

    timestamp = Timestamp(**timestamp_payload)
    if check_freshness and time.time() > timestamp.expires_at:
        result.add_error(
            ErrorCode.STALE_TIMESTAMP,
            f"Timestamp expired at {timestamp.expires_at}, now is {int(time.time())}",
            "timestamp.json",
        )

    # Rollback check
    if previous_snapshot:
        prev_version = previous_snapshot.get("version", 0)
        if timestamp.version < prev_version:
            result.add_error(
                ErrorCode.ROLLBACK,
                f"Timestamp version {timestamp.version} < previous {prev_version}",
                "timestamp.json",
            )

    # Verify snapshot
    snapshot_path = target / "snapshot.json"
    if not snapshot_path.exists():
        result.add_error(
            ErrorCode.INVALID_STRUCTURE, "Missing snapshot.json", str(snapshot_path)
        )
        return result

    snapshot_envelope = json.loads(snapshot_path.read_text())
    try:
        snapshot_payload = verify_envelope(snapshot_envelope, trusted_keys)
    except ValueError as e:
        result.add_error(
            ErrorCode.KEY_MISMATCH, f"Snapshot signature: {e}", "snapshot.json"
        )
        return result

    snapshot = Snapshot(**snapshot_payload)

    # Verify index
    index_path = target / "index.json"
    if not index_path.exists():
        result.add_error(
            ErrorCode.INVALID_STRUCTURE, "Missing index.json", str(index_path)
        )
        return result

    index_envelope = json.loads(index_path.read_text())
    try:
        index_payload = verify_envelope(index_envelope, trusted_keys)
    except ValueError as e:
        result.add_error(
            ErrorCode.KEY_MISMATCH, f"Index signature: {e}", "index.json"
        )
        return result

    # Verify index hash in snapshot
    index_canonical_hash = hash_bytes(canonicalize(index_payload))
    snapshot_index_hash = snapshot.files.get("index.json")
    if snapshot_index_hash and snapshot_index_hash != index_canonical_hash:
        result.add_error(
            ErrorCode.SNAPSHOT_MISMATCH,
            "index.json hash doesn't match snapshot",
            "index.json",
        )

    index = MarketplaceIndex(**index_payload)
    indexed_plugin_names = {p.name for p in index.plugins}

    # Verify each plugin
    plugins_dir = target / "plugins"
    if plugins_dir.exists():
        for plugin_dir in sorted(plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue

            plugin_name = plugin_dir.name

            # Check for unlisted content
            if plugin_name not in indexed_plugin_names:
                result.add_error(
                    ErrorCode.UNLISTED_CONTENT,
                    f"Plugin '{plugin_name}' exists on disk but not in signed index",
                    str(plugin_dir),
                )
                continue

            result.plugins_checked += 1

            # Verify versions file
            versions_path = plugin_dir / "versions.json"
            if not versions_path.exists():
                result.add_error(
                    ErrorCode.INVALID_STRUCTURE,
                    f"Missing versions.json for {plugin_name}",
                    str(versions_path),
                )
                continue

            versions_envelope = json.loads(versions_path.read_text())
            try:
                versions_payload = verify_envelope(versions_envelope, trusted_keys)
            except ValueError as e:
                result.add_error(
                    ErrorCode.KEY_MISMATCH,
                    f"versions.json signature for {plugin_name}: {e}",
                    str(versions_path),
                )
                continue

            # Check versions file in snapshot
            snapshot_key = f"plugins/{plugin_name}/versions.json"
            versions_hash = hash_bytes(canonicalize(versions_payload))
            if snapshot_key in snapshot.files:
                if snapshot.files[snapshot_key] != versions_hash:
                    result.add_error(
                        ErrorCode.SNAPSHOT_MISMATCH,
                        f"versions.json for {plugin_name} doesn't match snapshot",
                        str(versions_path),
                    )
            else:
                result.add_error(
                    ErrorCode.SNAPSHOT_MISMATCH,
                    f"{snapshot_key} not in snapshot",
                    str(versions_path),
                )

            plugin_versions = PluginVersions(**versions_payload)

            # Verify each version's artifact
            for ver in plugin_versions.versions:
                result.versions_checked += 1
                artifact_path = plugin_dir / ver.version / "artifact.zip"

                if not artifact_path.exists():
                    result.add_error(
                        ErrorCode.INVALID_STRUCTURE,
                        f"Missing artifact for {plugin_name}@{ver.version}",
                        str(artifact_path),
                    )
                    continue

                actual_hash = hash_file(artifact_path)
                if actual_hash != ver.artifact_hash:
                    result.add_error(
                        ErrorCode.HASH_MISMATCH,
                        f"Artifact hash mismatch for {plugin_name}@{ver.version}: "
                        f"expected {ver.artifact_hash[:16]}..., got {actual_hash[:16]}...",
                        str(artifact_path),
                    )

    return result
