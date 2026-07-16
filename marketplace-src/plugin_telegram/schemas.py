"""Normalized gateway envelope and outbound media shapes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class EnvelopeError(ValueError):
    """Raised when a gateway envelope is not contract-shaped."""


@dataclass(frozen=True)
class TelegramMedia:
    type: str
    file_id: str | None = None
    file_unique_id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    file_size: int | None = None
    url: str | None = None
    is_animated: bool | None = None
    is_video: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(
        cls, value: Any, *, default_type: str | None = None
    ) -> TelegramMedia | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise EnvelopeError("media must be an object or null")
        media_type = str(
            value.get("type") or value.get("kind") or default_type or ""
        ).strip()
        if not media_type:
            raise EnvelopeError("media.type is required")
        known = {
            "type", "kind", "file_id", "file_unique_id", "mime_type", "file_name",
            "width", "height", "duration", "size", "file_size", "url",
            "is_animated", "is_video",
        }
        return cls(
            type=media_type,
            file_id=_optional_str(value.get("file_id")),
            file_unique_id=_optional_str(value.get("file_unique_id")),
            mime_type=_optional_str(value.get("mime_type")),
            file_name=_optional_str(value.get("file_name")),
            width=_optional_int(value.get("width")),
            height=_optional_int(value.get("height")),
            duration=_optional_int(value.get("duration")),
            file_size=_optional_int(
                value.get("file_size")
                if value.get("file_size") is not None
                else value.get("size")
            ),
            url=_optional_str(value.get("url")),
            is_animated=_optional_bool(value.get("is_animated")),
            is_video=_optional_bool(value.get("is_video")),
            extra={key: item for key, item in value.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            key: value
            for key, value in asdict(self).items()
            if value is not None and key != "extra"
        }
        data.update(self.extra)
        return data

    @property
    def size(self) -> int | None:
        """Compatibility alias for pre-contract plugin callers."""
        return self.file_size


@dataclass(frozen=True)
class TelegramEnvelope:
    account: str
    event_type: str
    chat_id: str
    chat_kind: str
    sender_id: str | None
    tg_update_id: int
    tg_msg_id: int
    ts: str
    kind: str
    body: str | None = None
    chat_name: str | None = None
    sender_name: str | None = None
    reply_to_id: int | None = None
    mentioned_me: bool = False
    is_reply_to_me: bool = False
    is_command: bool = False
    edited: bool = False
    media: TelegramMedia | None = None
    reaction_emoji: str | None = None
    reaction_old: list[dict[str, Any]] = field(default_factory=list)
    reaction_new: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> TelegramEnvelope:
        if not isinstance(value, dict):
            raise EnvelopeError("envelope must be an object")
        missing = [
            key for key in ("chat_id", "tg_update_id", "tg_msg_id")
            if value.get(key) is None or str(value.get(key)).strip() == ""
        ]
        if missing:
            raise EnvelopeError(f"missing required fields: {', '.join(missing)}")
        chat_kind = str(value.get("chat_kind") or "").strip()
        if chat_kind not in {"dm", "group", "channel", "other"}:
            raise EnvelopeError("chat_kind must be dm, group, channel, or other")
        event_type = str(value.get("event_type") or "message").strip()
        if event_type not in {"message", "edit", "reaction"}:
            raise EnvelopeError("event_type must be message, edit, or reaction")
        raw = value.get("raw")
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise EnvelopeError("raw must be an object")
        try:
            update_id = int(value["tg_update_id"])
            message_id = int(value["tg_msg_id"])
        except (TypeError, ValueError) as exc:
            raise EnvelopeError("tg_update_id and tg_msg_id must be integers") from exc
        return cls(
            account=str(value.get("account") or "default"),
            event_type=event_type,
            chat_id=str(value["chat_id"]),
            chat_kind=chat_kind,
            chat_name=_optional_str(value.get("chat_name")),
            sender_id=_optional_str(value.get("sender_id")),
            sender_name=_optional_str(value.get("sender_name")),
            tg_update_id=update_id,
            tg_msg_id=message_id,
            reply_to_id=_optional_int(value.get("reply_to_id")),
            ts=str(value.get("ts") or ""),
            kind=str(value.get("kind") or "text"),
            body=_optional_str(value.get("body")),
            mentioned_me=bool(value.get("mentioned_me")),
            is_reply_to_me=bool(value.get("is_reply_to_me")),
            is_command=bool(value.get("is_command")),
            edited=bool(value.get("edited")),
            media=TelegramMedia.from_value(
                value.get("media"), default_type=str(value.get("kind") or "other")
            ),
            reaction_emoji=_optional_str(value.get("reaction_emoji")),
            reaction_old=_object_list(value.get("reaction_old")),
            reaction_new=_object_list(value.get("reaction_new")),
            raw=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.media is not None:
            data["media"] = self.media.to_dict()
        return data


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EnvelopeError(f"expected integer, got {value!r}") from exc


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _object_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EnvelopeError("reaction fields must be arrays")
    return [item for item in value if isinstance(item, dict)]
