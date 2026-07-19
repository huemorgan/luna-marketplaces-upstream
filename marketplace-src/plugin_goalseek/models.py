"""SQLAlchemy rows for plugin-goalseek. Namespaced ``goalseek_*`` — plugin
tables share core's database, so the prefix convention applies.

Nine tables (phases 01–06):

- ``goalseek_goals``    — one row per goal lifecycle (the source of truth).
- ``goalseek_steps``    — the living plan; ghost rows are abandoned branches.
- ``goalseek_facts``    — structured goal knowledge with an authority tag.
- ``goalseek_events``   — append-only evidence trail; every mutation lands here.
- ``goalseek_policies`` — policy rules (global + per-goal), phase 02.
- ``goalseek_grants``   — persistent owner grants, phase 02.
- ``goalseek_waits``    — parked async waits (owner reply / time / fact), phase 03.
- ``goalseek_settings`` — owner settings key/value (the config section), phase 05.
- ``goalseek_notes``    — narrative notes fallback when no wiki is installed, phase 06.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from luna_sdk import JSONB, UUID, declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class GoalRow(Base):
    """One goal lifecycle.

    ``stage`` moves through the whitelist in :mod:`lifecycle`. ``outcome`` is
    NULL until terminal, then one of the five base outcomes;
    ``outcome_label`` is the goal's own business label (must map to the base
    outcome through ``outcome_labels``). The full stage enum ships in phase 01
    (``parked``/``waiting``/``closing`` arrive behaviorally in later phases) so
    the schema never migrates for stages.
    """

    __tablename__ = "goalseek_goals"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    definition_of_done: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(String(16), default="active", nullable=False, index=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    outcome_reason: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # map: business label -> base outcome, defined at goal_open
    outcome_labels: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    autonomy_level: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    risk_ceiling: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # phase 03: heartbeat cadence for this goal's scheduler trigger. NULL =
    # the plugin default ("every day at 09:30"). Grammar is whatever the
    # installed plugin-scheduler parses — validated there, not here.
    cadence: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_by: Mapped[str] = mapped_column(String(16), default="owner", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class StepRow(Base):
    """One step of a goal's living plan.

    ``status``: planned | active | done | ghost. Ghost steps are abandoned
    branches — kept (not deleted) so the plan's evolution stays visible and
    the phase-05 Pursuit Map can fade them instead of losing them.
    """

    __tablename__ = "goalseek_steps"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    goal_id: Mapped[_uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="planned", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class FactRow(Base):
    """One structured fact the goal relies on.

    ``authority``: agent | human | system. The agent may create and update
    ``agent`` facts freely; ``human``/``system`` facts are read-only to it
    (the data-authority rule — enforced in tools.py in phase 01, by the
    policy engine from phase 02).
    """

    __tablename__ = "goalseek_facts"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    goal_id: Mapped[_uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    authority: Mapped[str] = mapped_column(String(16), default="agent", nullable=False)
    source: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PolicyRow(Base):
    """One policy rule. ``goal_id`` NULL = global (applies to every goal);
    a goal-scoped row extends/overrides the global ones for that goal.

    ``family`` is one of the eight families in :mod:`policy`. ``params`` is
    family-specific JSON (e.g. timing: {"working_hours": "9-17",
    "cooldown_minutes": 60, "window_cap": 5}).
    """

    __tablename__ = "goalseek_policies"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    goal_id: Mapped[_uuid.UUID | None] = mapped_column(UUID(), nullable=True, index=True)
    family: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(16), default="owner", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class GrantRow(Base):
    """A persistent owner grant, e.g. ``auto_approve_agent_goals``. Active
    while ``revoked_at`` is NULL. Append-only history: revoking sets the
    timestamp; a re-grant is a new row."""

    __tablename__ = "goalseek_grants"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    granted_by: Mapped[str] = mapped_column(String(32), default="owner", nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WaitRow(Base):
    """One async wait: the goal parks until a condition resolves.

    ``kind``: owner_reply | until_time | fact_present | manual.
    ``params``: kind-specific — until_time: {"until": iso}; fact_present:
    {"fact_key": str}; owner_reply: {"conversation_id": str|None}.
    ``status``: open | met | timed_out | cancelled.
    """

    __tablename__ = "goalseek_waits"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    goal_id: Mapped[_uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    keep_heartbeat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventRow(Base):
    """Append-only evidence trail. ``kind`` in phase 01: opened, approved,
    stage_change, updated, step_change, fact_set, note, closed. Phase 02 adds
    effect_requested, effect_attempted, effect_confirmed, effect_failed,
    effect_rejected, policy_block, policy_set, grant_written, grant_revoked —
    same table, no migration."""

    __tablename__ = "goalseek_events"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    goal_id: Mapped[_uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


class SettingRow(Base):
    """One owner setting (the phase-05 config section). Key/value so new
    settings never migrate the schema; defaults live in :mod:`settings`."""

    __tablename__ = "goalseek_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class NoteRow(Base):
    """One narrative note (phase 06, backend 3 of the knowledge chain): the
    same content ``knowledge.write_note`` would put on a wiki page, kept
    locally when neither curiosity's mission wiki nor plugin-wiki exists."""

    __tablename__ = "goalseek_notes"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(), primary_key=True, default=_uuid.uuid4)
    goal_id: Mapped[_uuid.UUID] = mapped_column(UUID(), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


ALL_TABLES = (
    GoalRow.__table__,
    StepRow.__table__,
    FactRow.__table__,
    EventRow.__table__,
    PolicyRow.__table__,
    GrantRow.__table__,
    WaitRow.__table__,
    SettingRow.__table__,
    NoteRow.__table__,
)
