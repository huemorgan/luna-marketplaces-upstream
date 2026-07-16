"""Bounded, attributed Telegram cross-chat context."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def select_window(
    messages: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    minutes: int = 5,
    max_messages: int = 30,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() - max(0, minutes) * 60
    ordered = sorted(messages, key=_timestamp, reverse=True)
    selected = [
        message
        for index, message in enumerate(ordered)
        if _timestamp(message) >= cutoff or index < max(0, max_messages)
    ]
    selected.reverse()
    return selected


def build_context_block(
    messages: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    minutes: int = 5,
    max_messages: int = 30,
) -> str:
    now = now or datetime.now(timezone.utc)
    lines: list[str] = []
    for message in select_window(
        messages, now=now, minutes=minutes, max_messages=max_messages
    ):
        timestamp = _datetime(message["ts"])
        delta = _humanize(max(0, now.timestamp() - timestamp.timestamp()))
        chat = message.get("chat_name") or message.get("chat_id") or "chat"
        sender = (
            "Luna"
            if message.get("from_me")
            else message.get("sender_name") or message.get("sender_id") or "someone"
        )
        body = str(message.get("body") or "").strip()
        if not body:
            media = message.get("media_json") or {}
            body = f"<{media.get('type') or message.get('kind') or 'message'}>"
        lines.append(f"[{chat} · {sender} · {delta} ago] {body}")
    return "\n".join(lines)


def _datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _timestamp(message: dict[str, Any]) -> float:
    return _datetime(message["ts"]).timestamp()


def _humanize(seconds: float) -> str:
    value = int(seconds)
    if value < 60:
        return f"{value}s"
    if value < 3600:
        return f"{value // 60}m"
    if value < 86400:
        return f"{value // 3600}h"
    return f"{value // 86400}d"
