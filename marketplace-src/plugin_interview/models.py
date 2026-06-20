"""SQLAlchemy rows for plugin-interview. All tables are `plugin_interview_*`
and created idempotently in on_load (mirrors plugin-memory)."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from luna_sdk import JSONB, UUID, declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InterviewSession(Base):
    __tablename__ = "plugin_interview_sessions"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    domain_brief: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    target_min: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    target_pct: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    coverage_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class InterviewTopic(Base):
    __tablename__ = "plugin_interview_topics"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    interview_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("plugin_interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    why: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    coverage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="agent", nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (Index("ix_plugin_interview_topics_iv", "interview_id", "key"),)


class InterviewTurn(Base):
    __tablename__ = "plugin_interview_turns"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    interview_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("plugin_interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    question: Mapped[str] = mapped_column(Text, default="", nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    touched: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    constraints: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


ALL_TABLES = (
    InterviewSession.__table__,
    InterviewTopic.__table__,
    InterviewTurn.__table__,
)
