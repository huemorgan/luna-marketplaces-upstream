"""Timestamped HMAC shared with luna-tg-gateway."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import time

SKEW_SECONDS = 300


def sign(secret: str, raw_body: str, timestamp: str | None = None) -> tuple[str, str]:
    ts = timestamp or str(int(time.time()))
    signature = _hmac.new(
        secret.encode("utf-8"),
        f"{ts}.{raw_body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return ts, signature


def verify(
    secret: str,
    raw_body: str,
    timestamp: str | None,
    signature: str | None,
    *,
    now: int | None = None,
) -> bool:
    if not timestamp or not signature:
        return False
    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((now if now is not None else int(time.time())) - timestamp_int) > SKEW_SECONDS:
        return False
    expected = _hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{raw_body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _hmac.compare_digest(expected, signature)
