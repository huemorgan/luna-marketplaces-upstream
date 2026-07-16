"""Telegram DM and group activation policy."""

from __future__ import annotations

import re
from collections.abc import Iterable

_LUNA_COMMAND = re.compile(r"^\s*/luna(?:@[A-Za-z0-9_]+)?(?:\s|$)", re.IGNORECASE)


def should_respond(
    envelope: dict,
    allowlist: Iterable[str] | None = None,
    *,
    reaction_targets_me: bool = False,
) -> bool:
    chat_kind = envelope.get("chat_kind")
    if chat_kind not in {"dm", "group"}:
        return False
    if envelope.get("event_type") == "reaction":
        if not reaction_targets_me:
            return False
        if chat_kind == "group":
            return True
    if chat_kind == "dm":
        allowed = {str(value).strip() for value in allowlist or [] if str(value).strip()}
        return not allowed or str(envelope.get("chat_id") or "") in allowed
    if chat_kind == "group":
        return bool(
            envelope.get("mentioned_me")
            or envelope.get("is_reply_to_me")
            or envelope.get("is_command")
            or is_luna_command(envelope.get("body"))
        )
    return False


def is_luna_command(body: object) -> bool:
    return bool(_LUNA_COMMAND.match(str(body or "")))
