"""Cryptographic signing and verification for Luna marketplaces.

Uses Ed25519 (via PyNaCl) with canonical JSON (RFC 8785) serialization
and DSSE-inspired signature envelopes.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import canonicaljson
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey


@dataclass(frozen=True)
class KeyPair:
    signing_key: SigningKey
    verify_key: VerifyKey

    @classmethod
    def generate(cls) -> "KeyPair":
        sk = SigningKey.generate()
        return cls(signing_key=sk, verify_key=sk.verify_key)

    @classmethod
    def from_file(cls, path: Path) -> "KeyPair":
        data = path.read_bytes()
        sk = SigningKey(data)
        return cls(signing_key=sk, verify_key=sk.verify_key)

    def save(self, directory: Path, name: str = "marketplace") -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.key").write_bytes(bytes(self.signing_key))
        (directory / f"{name}.pub").write_text(
            self.verify_key.encode(encoder=HexEncoder).decode()
        )

    @property
    def public_hex(self) -> str:
        return self.verify_key.encode(encoder=HexEncoder).decode()


def canonicalize(obj: dict | list) -> bytes:
    """Canonical JSON serialization (RFC 8785)."""
    return canonicaljson.encode_canonical_json(obj)


def sign_payload(payload: dict | list, signing_key: SigningKey) -> dict:
    """Sign a JSON-serializable payload, return a DSSE-style envelope."""
    payload_bytes = canonicalize(payload)
    signature = signing_key.sign(payload_bytes, encoder=HexEncoder).signature.decode()
    return {
        "payload": payload,
        "signatures": [
            {
                "keyid": signing_key.verify_key.encode(encoder=HexEncoder).decode(),
                "sig": signature,
            }
        ],
    }


def verify_envelope(envelope: dict, trusted_keys: list[str]) -> dict:
    """Verify a signed envelope against a list of trusted public key hex strings.

    Returns the payload if any signature matches a trusted key.
    Raises ValueError on verification failure.
    """
    payload = envelope.get("payload")
    signatures = envelope.get("signatures", [])

    if not payload or not signatures:
        raise ValueError("Invalid envelope: missing payload or signatures")

    payload_bytes = canonicalize(payload)

    for sig_entry in signatures:
        keyid = sig_entry.get("keyid", "")
        sig_hex = sig_entry.get("sig", "")

        if keyid in trusted_keys:
            try:
                vk = VerifyKey(keyid.encode(), encoder=HexEncoder)
                vk.verify(payload_bytes, bytes.fromhex(sig_hex))
                return payload
            except Exception:
                raise ValueError(f"Signature verification failed for key {keyid[:16]}...")

    raise ValueError(
        f"No signature from a trusted key. "
        f"Envelope keys: {[s.get('keyid', '')[:16] for s in signatures]}"
    )


def hash_file(path: Path) -> str:
    """SHA-256 hash of a file, hex-encoded."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    """SHA-256 hash of bytes, hex-encoded."""
    return hashlib.sha256(data).hexdigest()


def make_timestamp(freshness_days: int = 7) -> dict:
    """Create a timestamp document with expiry."""
    now = int(time.time())
    return {
        "signed_at": now,
        "expires_at": now + (freshness_days * 86400),
        "version": 1,
    }
