"""Parse agent reply directives and generated media references."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any
from urllib.parse import urlparse

_REPLY = re.compile(r"\[\[reply\]\]", re.IGNORECASE)
_REACT = re.compile(r"\[\[react:([^\]\r\n]+)\]\]", re.IGNORECASE)
_TYPED_MEDIA = re.compile(
    r"\[\[media:(photo|animation|video|voice|audio|document|sticker):(.+?)\]\]",
    re.IGNORECASE,
)
_MEDIA = re.compile(r"\[\[media:(.+?)\]\]", re.IGNORECASE)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_MARKDOWN_FILE = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")

_EXTENSION_TYPES = {
    ".jpg": "photo",
    ".jpeg": "photo",
    ".png": "photo",
    ".webp": "photo",
    ".gif": "animation",
    ".mp4": "video",
    ".mov": "video",
    ".ogg": "voice",
    ".opus": "voice",
    ".mp3": "audio",
    ".m4a": "audio",
}


@dataclass(frozen=True)
class OutboundMedia:
    media_type: str
    source: str


@dataclass(frozen=True)
class ParsedReply:
    text: str
    reply: bool
    reaction: str | None
    media: tuple[OutboundMedia, ...]


def parse_turn_result(result: Any) -> ParsedReply:
    text, structured_media = _result_parts(result)
    reply = bool(_REPLY.search(text))
    reaction_match = _REACT.search(text)
    reaction = reaction_match.group(1).strip() if reaction_match else None
    media = list(structured_media)

    for match in _TYPED_MEDIA.finditer(text):
        media.append(OutboundMedia(match.group(1).lower(), match.group(2).strip()))
    text = _TYPED_MEDIA.sub("", text)

    for match in _MEDIA.finditer(text):
        source = match.group(1).strip()
        media.append(OutboundMedia(_infer_type(source), source))
    text = _MEDIA.sub("", text)

    for pattern in (_MARKDOWN_IMAGE, _MARKDOWN_FILE):
        for match in pattern.finditer(text):
            source = match.group(1).strip()
            if pattern is _MARKDOWN_IMAGE or _looks_like_media_reference(source):
                media.append(OutboundMedia(_infer_type(source), source))
                text = text.replace(match.group(0), "")

    text = _REPLY.sub("", text)
    text = _REACT.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return ParsedReply(
        text=text,
        reply=reply,
        reaction=reaction,
        media=tuple(_deduplicate(media)),
    )


def _result_parts(result: Any) -> tuple[str, list[OutboundMedia]]:
    if isinstance(result, str):
        return result, []
    if result is None:
        return "", []
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False), []
    text = result.get("text") or result.get("content") or result.get("message") or ""
    values: list[Any] = []
    for key in ("media", "attachments", "files", "images"):
        value = result.get(key)
        if value is not None:
            values.extend(value if isinstance(value, list) else [value])
    media: list[OutboundMedia] = []
    for value in values:
        item = _structured_media(value)
        if item is not None:
            media.append(item)
    return str(text), media


def _structured_media(value: Any) -> OutboundMedia | None:
    if isinstance(value, str):
        return OutboundMedia(_infer_type(value), value)
    if not isinstance(value, dict):
        return None
    source = (
        value.get("source")
        or value.get("url")
        or value.get("file_id")
        or value.get("path")
        or value.get("ref")
    )
    if not source:
        return None
    media_type = str(value.get("type") or value.get("kind") or _infer_type(str(source)))
    return OutboundMedia(media_type, str(source))


def _infer_type(source: str) -> str:
    path = urlparse(source).path if "://" in source else source
    return _EXTENSION_TYPES.get(PurePath(path).suffix.lower(), "document")


def _looks_like_media_reference(source: str) -> bool:
    if source.startswith(("sandbox:/", "file:/", "/")):
        return True
    path = urlparse(source).path
    return PurePath(path).suffix.lower() in set(_EXTENSION_TYPES) | {
        ".pdf", ".zip", ".txt", ".csv", ".doc", ".docx"
    }


def _deduplicate(media: list[OutboundMedia]) -> list[OutboundMedia]:
    result: list[OutboundMedia] = []
    seen: set[tuple[str, str]] = set()
    for item in media:
        key = (item.media_type, item.source)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
