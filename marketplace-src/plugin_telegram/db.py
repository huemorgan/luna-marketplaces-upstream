"""Plugin-local Telegram context store."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    inspect,
    insert,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from luna_sdk import UUID, declarative_base

Base = declarative_base()


class TelegramMessage(Base):
    __tablename__ = "telegram_plugin_messages_v2"
    __table_args__ = (
        UniqueConstraint(
            "account", "tg_update_id", name="uq_tg_plugin_account_update"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    account: Mapped[str] = mapped_column(String(64), default="default")
    event_type: Mapped[str] = mapped_column(String(16), default="message")
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    chat_kind: Mapped[str] = mapped_column(String(16))
    chat_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sender_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    from_me: Mapped[bool] = mapped_column(Boolean, default=False)
    tg_update_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    tg_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reply_to_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="text")
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    mentioned_me: Mapped[bool] = mapped_column(Boolean, default=False)
    is_reply_to_me: Mapped[bool] = mapped_column(Boolean, default=False)
    is_command: Mapped[bool] = mapped_column(Boolean, default=False)
    reaction_emoji: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reaction_old_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    reaction_new_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    media_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


_T = TelegramMessage.__table__


async def create_tables(engine) -> None:
    async with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            await connection.run_sync(table.create, checkfirst=True)
        await connection.run_sync(_copy_legacy_rows)


def _copy_legacy_rows(connection) -> None:
    """Copy v0.1 rows into v0.2 storage without altering the legacy table."""
    legacy_name = "telegram_plugin_messages"
    inspector = inspect(connection)
    if legacy_name not in inspector.get_table_names():
        return
    legacy = Table(legacy_name, MetaData(), autoload_with=connection)
    common = set(legacy.c.keys()) & set(_T.c.keys())
    existing_ids = set(connection.execute(select(_T.c.id)).scalars())
    for row in connection.execute(select(legacy)).mappings():
        row_id = row.get("id")
        if isinstance(row_id, str):
            row_id = uuid.UUID(row_id)
        if row_id in existing_ids:
            continue
        values = {key: row[key] for key in common}
        values["id"] = row_id
        values.setdefault("account", "default")
        values.setdefault("event_type", "message")
        values.setdefault("edited", False)
        values.setdefault("mentioned_me", False)
        values.setdefault("is_reply_to_me", False)
        values.setdefault("is_command", False)
        connection.execute(insert(_T).values(**values))
        existing_ids.add(row_id)


async def record_message(engine, **fields: Any) -> bool:
    """Insert a context event, idempotently when ``tg_update_id`` is present."""
    fields.setdefault("id", uuid.uuid4())
    fields.setdefault("ts", datetime.now(timezone.utc))
    try:
        async with engine.begin() as connection:
            await connection.execute(insert(_T).values(**fields))
    except IntegrityError:
        if fields.get("tg_update_id") is not None:
            return False
        raise
    return True


async def recent_messages(
    engine,
    *,
    limit: int = 80,
    chat_id: str | None = None,
    account: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    statement = select(
        _T.c.chat_id,
        _T.c.chat_name,
        _T.c.chat_kind,
        _T.c.event_type,
        _T.c.sender_id,
        _T.c.sender_name,
        _T.c.from_me,
        _T.c.tg_msg_id,
        _T.c.reply_to_id,
        _T.c.body,
        _T.c.ts,
        _T.c.kind,
        _T.c.reaction_emoji,
        _T.c.media_json,
    ).order_by(_T.c.ts.desc()).limit(limit)
    if chat_id is not None:
        statement = statement.where(_T.c.chat_id == str(chat_id))
    if account is not None:
        statement = statement.where(_T.c.account == str(account))
    async with engine.connect() as connection:
        rows = (await connection.execute(statement)).mappings().all()
    return [dict(row) for row in rows]


async def find_message(
    engine,
    *,
    chat_id: str,
    tg_msg_id: int,
    from_me: bool | None = None,
    account: str | None = None,
) -> dict[str, Any] | None:
    """Find the latest stored message for a chat-local Telegram message ID."""
    statement = (
        select(
            _T.c.chat_id,
            _T.c.chat_name,
            _T.c.chat_kind,
            _T.c.sender_id,
            _T.c.sender_name,
            _T.c.from_me,
            _T.c.tg_msg_id,
            _T.c.body,
            _T.c.ts,
            _T.c.kind,
            _T.c.media_json,
        )
        .where(
            _T.c.chat_id == str(chat_id),
            _T.c.tg_msg_id == int(tg_msg_id),
            _T.c.event_type != "reaction",
        )
        .order_by(_T.c.ts.desc())
        .limit(1)
    )
    if from_me is not None:
        statement = statement.where(_T.c.from_me == from_me)
    if account is not None:
        statement = statement.where(_T.c.account == str(account))
    async with engine.connect() as connection:
        row = (await connection.execute(statement)).mappings().first()
    return dict(row) if row is not None else None


async def list_chats(
    engine, *, limit: int = 50, account: str | None = None
) -> list[dict[str, Any]]:
    rows = await recent_messages(engine, limit=500, account=account)
    chats: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        chat_id = row["chat_id"]
        if chat_id in seen:
            continue
        seen.add(chat_id)
        chats.append(
            {
                "chat_id": chat_id,
                "chat_kind": row["chat_kind"],
                "chat_name": row["chat_name"],
                "last_activity": row["ts"].isoformat(),
            }
        )
        if len(chats) >= max(1, min(int(limit), 100)):
            break
    return chats


async def resolve_chat(
    engine, target: str, *, account: str | None = None
) -> dict[str, Any]:
    """Resolve a numeric ID or a unique, case-insensitive known chat name."""
    value = str(target).strip()
    if not value:
        raise ValueError("chat target is required")
    chats = await list_chats(engine, limit=100, account=account)
    by_id = next((chat for chat in chats if chat["chat_id"] == value), None)
    if by_id is not None:
        return by_id
    if _is_numeric_chat_id(value):
        return {"chat_id": value, "chat_kind": "unknown", "chat_name": None}
    matches = [
        chat for chat in chats
        if (chat.get("chat_name") or "").casefold() == value.casefold()
    ]
    if not matches:
        raise ValueError(f"unknown Telegram chat: {value}")
    if len(matches) > 1:
        ids = ", ".join(chat["chat_id"] for chat in matches)
        raise ValueError(f"ambiguous Telegram chat name {value!r}; use one of: {ids}")
    return matches[0]


def _is_numeric_chat_id(value: str) -> bool:
    return value.lstrip("-").isdigit()
