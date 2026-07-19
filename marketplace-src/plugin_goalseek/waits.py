"""Async waits — a goal parks itself until the world answers.

Four condition kinds (v1): ``owner_reply`` (an owner message arrives),
``until_time`` (a wall-clock instant), ``fact_present`` (a named goal fact is
written), ``manual`` (the agent calls goal_wait_resolve). Opening a wait moves
the goal ``active → waiting``; resolving (or timing out) moves it back and the
caller sends the muted resume wake.

The store is pure DB logic — trigger creation for ``until_time`` and the
muted resume are wired by ``__init__`` so this module stays sdk-free and
unit-testable on SQLite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .models import EventRow, GoalRow, WaitRow

WAIT_KINDS = ("owner_reply", "until_time", "fact_present", "manual")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _wait_dict(w: WaitRow) -> dict[str, Any]:
    return {
        "id": str(w.id),
        "goal_id": str(w.goal_id),
        "description": w.description,
        "kind": w.kind,
        "params": w.params or {},
        "status": w.status,
        "keep_heartbeat": w.keep_heartbeat,
        "timeout_at": w.timeout_at.isoformat() if w.timeout_at else None,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "resolved_at": w.resolved_at.isoformat() if w.resolved_at else None,
    }


def _parse_when(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO date/datetime, got {value!r}") from None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


class WaitStore:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    @staticmethod
    def _event(s, goal_id: uuid.UUID, kind: str, payload: dict | None = None) -> None:
        s.add(EventRow(goal_id=goal_id, kind=kind, payload=payload or {}))

    async def open(
        self,
        *,
        goal_id: str,
        description: str,
        kind: str,
        until: str | None = None,
        fact_key: str | None = None,
        timeout: str | None = None,
        keep_heartbeat: bool = False,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in WAIT_KINDS:
            raise ValueError(f"wait kind must be one of {WAIT_KINDS}, got {kind!r}")
        if not (description or "").strip():
            raise ValueError("description must be non-empty — say what you are waiting for")
        params: dict[str, Any] = {}
        if kind == "until_time":
            if not until:
                raise ValueError("an until_time wait needs 'until' (ISO date/datetime)")
            when = _parse_when(until, "until")
            if when <= datetime.now(UTC):
                raise ValueError(f"'until' is in the past ({until}) — nothing to wait for")
            params["until"] = when.isoformat()
        if kind == "fact_present":
            if not (fact_key or "").strip():
                raise ValueError("a fact_present wait needs 'fact_key'")
            params["fact_key"] = fact_key.strip()
        if kind == "owner_reply" and conversation_id:
            params["conversation_id"] = str(conversation_id)
        timeout_at = _parse_when(timeout, "timeout") if timeout else None

        async with self._sf() as s:
            gid = uuid.UUID(str(goal_id))
            goal = await s.get(GoalRow, gid)
            if goal is None:
                raise LookupError(f"no goal with id {goal_id}")
            if goal.stage == "closed":
                raise ValueError("goal is closed — closed goals cannot wait")
            if goal.stage not in ("active", "waiting"):
                raise ValueError(f"only an active goal can wait (stage is {goal.stage!r})")
            w = WaitRow(
                goal_id=gid,
                description=description.strip(),
                kind=kind,
                params=params,
                keep_heartbeat=bool(keep_heartbeat),
                timeout_at=timeout_at,
            )
            s.add(w)
            await s.flush()
            if goal.stage == "active":
                self._event(s, gid, "stage_change", {"from": "active", "to": "waiting"})
                goal.stage = "waiting"
            self._event(
                s, gid, "wait_opened",
                {"wait_id": str(w.id), "kind": kind, "description": w.description,
                 **({"until": params["until"]} if "until" in params else {}),
                 **({"fact_key": params["fact_key"]} if "fact_key" in params else {})},
            )
            await s.commit()
            return _wait_dict(w)

    async def _resolve_row(self, s, w: WaitRow, *, status: str, note: str = "") -> dict[str, Any]:
        w.status = status
        w.resolved_at = datetime.now(UTC)
        goal = await s.get(GoalRow, w.goal_id)
        goal_reactivated = False
        if goal is not None and goal.stage == "waiting":
            remaining = (
                await s.execute(
                    select(WaitRow).where(
                        WaitRow.goal_id == w.goal_id,
                        WaitRow.status == "open",
                        WaitRow.id != w.id,
                    )
                )
            ).scalars().first()
            if remaining is None:
                self._event(s, w.goal_id, "stage_change", {"from": "waiting", "to": "active"})
                goal.stage = "active"
                goal_reactivated = True
        self._event(
            s, w.goal_id,
            "wait_resolved" if status == "met" else f"wait_{status}",
            {"wait_id": str(w.id), "kind": w.kind, "description": w.description,
             **({"note": note} if note else {})},
        )
        out = _wait_dict(w)
        out["goal_reactivated"] = goal_reactivated
        return out

    async def resolve(self, wait_id: str, *, note: str = "") -> dict[str, Any]:
        async with self._sf() as s:
            try:
                w = await s.get(WaitRow, uuid.UUID(str(wait_id)))
            except ValueError:
                raise LookupError(f"no wait with id {wait_id}") from None
            if w is None:
                raise LookupError(f"no wait with id {wait_id}")
            if w.status != "open":
                return _wait_dict(w)  # idempotent: already resolved
            out = await self._resolve_row(s, w, status="met", note=note)
            await s.commit()
            return out

    async def cancel(self, wait_id: str, *, note: str = "") -> dict[str, Any]:
        async with self._sf() as s:
            w = await s.get(WaitRow, uuid.UUID(str(wait_id)))
            if w is None:
                raise LookupError(f"no wait with id {wait_id}")
            if w.status != "open":
                return _wait_dict(w)
            out = await self._resolve_row(s, w, status="cancelled", note=note)
            await s.commit()
            return out

    async def list_open(self, goal_id: str | None = None) -> list[dict[str, Any]]:
        async with self._sf() as s:
            q = select(WaitRow).where(WaitRow.status == "open").order_by(WaitRow.created_at)
            if goal_id:
                q = q.where(WaitRow.goal_id == uuid.UUID(str(goal_id)))
            rows = (await s.execute(q)).scalars().all()
            return [_wait_dict(w) for w in rows]

    async def resolve_owner_reply(self, conversation_id: str | None) -> list[dict[str, Any]]:
        """Resolve open owner_reply waits matched to this conversation (waits
        bound to a conversation only resolve on THAT conversation; unbound
        waits resolve on any owner turn). Returns the resolved waits."""
        resolved: list[dict[str, Any]] = []
        async with self._sf() as s:
            rows = (
                await s.execute(
                    select(WaitRow).where(WaitRow.status == "open", WaitRow.kind == "owner_reply")
                )
            ).scalars().all()
            for w in rows:
                bound = (w.params or {}).get("conversation_id")
                if bound and conversation_id and str(bound) != str(conversation_id):
                    continue
                resolved.append(await self._resolve_row(s, w, status="met", note="owner replied"))
            if resolved:
                await s.commit()
        return resolved

    async def resolve_fact_present(self, goal_id: str, fact_key: str) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        async with self._sf() as s:
            rows = (
                await s.execute(
                    select(WaitRow).where(
                        WaitRow.status == "open",
                        WaitRow.kind == "fact_present",
                        WaitRow.goal_id == uuid.UUID(str(goal_id)),
                    )
                )
            ).scalars().all()
            for w in rows:
                if (w.params or {}).get("fact_key") == fact_key:
                    resolved.append(
                        await self._resolve_row(s, w, status="met", note=f"fact {fact_key!r} written")
                    )
            if resolved:
                await s.commit()
        return resolved

    async def sweep_due(self, now: datetime | None = None) -> dict[str, list[dict[str, Any]]]:
        """Time-based bookkeeping: until_time waits whose instant passed
        resolve as met; any wait past its timeout_at times out. Returns both
        lists so the caller can wake the affected goals."""
        now = now or datetime.now(UTC)
        met: list[dict[str, Any]] = []
        timed_out: list[dict[str, Any]] = []
        async with self._sf() as s:
            rows = (
                await s.execute(select(WaitRow).where(WaitRow.status == "open"))
            ).scalars().all()
            for w in rows:
                if w.kind == "until_time":
                    until = _parse_when((w.params or {}).get("until", ""), "until") \
                        if (w.params or {}).get("until") else None
                    if until is not None and until <= now:
                        met.append(await self._resolve_row(s, w, status="met", note="time reached"))
                        continue
                t_at = _aware(w.timeout_at)
                if t_at is not None and t_at <= now:
                    timed_out.append(
                        await self._resolve_row(s, w, status="timed_out",
                                                note="wait timed out — decide the next move")
                    )
            if met or timed_out:
                await s.commit()
        return {"met": met, "timed_out": timed_out}
