"""The goal store and the six phase-01 tools.

Every mutation appends a ``goalseek_events`` row — the evidence trail is not
optional. Terminal goals reject every mutation (lifecycle invariant).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .lifecycle import (
    can_transition,
    is_terminal,
    validate_close,
    validate_open,
)
from .models import EventRow, FactRow, GoalRow, StepRow

# Phase 03: at most this many goals run heartbeats at once. Constant until the
# phase-05 settings UI makes it configurable (3-option setting).
MAX_ACTIVE_GOALS = 5


def _parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _goal_dict(g: GoalRow) -> dict[str, Any]:
    return {
        "id": str(g.id),
        "statement": g.statement,
        "definition_of_done": g.definition_of_done,
        "stage": g.stage,
        "outcome": g.outcome,
        "outcome_label": g.outcome_label,
        "outcome_reason": g.outcome_reason,
        "outcome_labels": g.outcome_labels or {},
        "autonomy_level": g.autonomy_level,
        "risk_ceiling": g.risk_ceiling,
        "deadline": g.deadline.isoformat() if g.deadline else None,
        "cadence": g.cadence,
        "opened_by": g.opened_by,
        "approved_at": g.approved_at.isoformat() if g.approved_at else None,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }


def _step_dict(s: StepRow) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "seq": s.seq,
        "title": s.title,
        "status": s.status,
        "note": s.note,
    }


def _fact_dict(f: FactRow) -> dict[str, Any]:
    return {
        "key": f.key,
        "value": f.value,
        "authority": f.authority,
        "source": f.source,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
    }


def _uuid_of(goal_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(goal_id))
    except ValueError:
        raise LookupError(f"no goal with id {goal_id}") from None


class GoalseekStore:
    """All DB access for goal-seek. One store, one session factory."""

    def __init__(self, session_factory, settings=None) -> None:
        self._sf = session_factory
        # Phase 05: SettingsStore. None (tests, older wiring) → constants.
        self._settings = settings

    async def _cap(self) -> int:
        if self._settings is None:
            return MAX_ACTIVE_GOALS
        try:
            return int(await self._settings.get("max_active_goals"))
        except Exception:  # noqa: BLE001 — settings failure must not block goals
            return MAX_ACTIVE_GOALS

    async def default_autonomy(self) -> int:
        if self._settings is None:
            return 3
        try:
            return int(await self._settings.get("default_autonomy_level"))
        except Exception:  # noqa: BLE001
            return 3

    # -- internals ---------------------------------------------------------

    async def _get(self, s, goal_id: str) -> GoalRow:
        g = await s.get(GoalRow, _uuid_of(goal_id))
        if g is None:
            raise LookupError(f"no goal with id {goal_id}")
        return g

    @staticmethod
    def _event(s, goal_id: uuid.UUID, kind: str, payload: dict | None = None) -> None:
        s.add(EventRow(goal_id=goal_id, kind=kind, payload=payload or {}))

    # -- lifecycle ---------------------------------------------------------

    async def open(
        self,
        *,
        statement: str,
        definition_of_done: str,
        deadline: str | None = None,
        autonomy_level: int = 3,
        risk_ceiling: str = "medium",
        outcome_labels: dict[str, str] | None = None,
        steps: list[str] | None = None,
        opened_by: str = "owner",
        approved_via: str | None = None,
        cadence: str | None = None,
    ) -> dict[str, Any]:
        err = validate_open(
            statement=statement,
            definition_of_done=definition_of_done,
            autonomy_level=int(autonomy_level),
            risk_ceiling=risk_ceiling,
            outcome_labels=outcome_labels,
        )
        if err:
            raise ValueError(err)
        # Agent-opened goals park in `proposed` unless an approval path already
        # cleared them (phase 02: approval card or the persistent grant —
        # ``approved_via`` records which).
        approved = opened_by == "owner" or approved_via is not None
        stage = "active" if approved else "proposed"
        cap = await self._cap()
        async with self._sf() as s:
            # Concurrency cap (phase 03): a goal beyond the cap opens parked —
            # never rejected, just not running a heartbeat until a slot frees.
            over_cap = False
            if stage == "active":
                active_count = len(
                    (
                        await s.execute(select(GoalRow).where(GoalRow.stage == "active"))
                    ).scalars().all()
                )
                if active_count >= cap:
                    stage = "parked"
                    over_cap = True
            g = GoalRow(
                statement=statement.strip(),
                definition_of_done=definition_of_done.strip(),
                stage=stage,
                outcome_labels=outcome_labels or {},
                autonomy_level=int(autonomy_level),
                risk_ceiling=risk_ceiling,
                deadline=_parse_deadline(deadline),
                cadence=(cadence or "").strip() or None,
                opened_by=opened_by,
                approved_at=datetime.now(UTC) if approved else None,
            )
            s.add(g)
            await s.flush()
            for i, title in enumerate(steps or []):
                if str(title).strip():
                    s.add(StepRow(goal_id=g.id, seq=i, title=str(title).strip()))
            self._event(
                s, g.id, "opened",
                {"opened_by": opened_by, "stage": stage, "statement": g.statement},
            )
            if over_cap:
                self._event(
                    s, g.id, "parked_over_cap",
                    {"cap": cap,
                     "note": "opened parked — active-goal cap reached; "
                             "activate it after another goal closes or parks"},
                )
            if approved_via:
                self._event(s, g.id, "approved", {"via": approved_via})
            await s.commit()
            out = _goal_dict(g)
            if opened_by == "agent":
                # Tell the model HOW the open was cleared so it reports honestly
                # ("standing grant, no card" vs "owner approved a card").
                out["approved_via"] = approved_via or "pending_owner_ratification"
            if over_cap:
                out["parked_over_cap"] = True
                out["note"] = (
                    f"active-goal cap ({cap}) reached — this goal "
                    "opened parked; activate it when a slot frees"
                )
            return out

    # -- policies (phase 02) -------------------------------------------------

    async def policy_set(
        self,
        *,
        family: str,
        params: dict[str, Any],
        goal_id: str | None = None,
        enabled: bool = True,
        created_by: str = "owner",
    ) -> dict[str, Any]:
        from .models import PolicyRow
        from .policy import FAMILIES

        if family not in FAMILIES:
            raise ValueError(f"unknown policy family {family!r} — one of {FAMILIES}")
        if not isinstance(params, dict):
            raise ValueError("params must be an object of family-specific settings")
        gid = _uuid_of(goal_id) if goal_id else None
        async with self._sf() as s:
            if gid is not None:
                goal = await s.get(GoalRow, gid)
                if goal is None:
                    raise LookupError(f"no goal with id {goal_id}")
            from sqlalchemy import select as _select

            existing = (
                await s.execute(
                    _select(PolicyRow).where(
                        PolicyRow.family == family,
                        PolicyRow.goal_id == gid if gid is not None else PolicyRow.goal_id.is_(None),
                    )
                )
            ).scalars().first()
            if existing is not None:
                existing.params = params
                existing.enabled = bool(enabled)
                row = existing
            else:
                row = PolicyRow(
                    goal_id=gid, family=family, params=params,
                    enabled=bool(enabled), created_by=created_by,
                )
                s.add(row)
            await s.flush()
            if gid is not None:
                self._event(
                    s, gid, "policy_set",
                    {"family": family, "params": params, "enabled": bool(enabled)},
                )
            await s.commit()
            return {
                "id": str(row.id),
                "goal_id": str(row.goal_id) if row.goal_id else None,
                "family": row.family,
                "params": row.params,
                "enabled": row.enabled,
            }

    async def policy_list(self, goal_id: str | None = None) -> list[dict[str, Any]]:
        from sqlalchemy import select as _select

        from .models import PolicyRow

        async with self._sf() as s:
            q = _select(PolicyRow)
            if goal_id:
                gid = _uuid_of(goal_id)
                q = q.where((PolicyRow.goal_id == gid) | (PolicyRow.goal_id.is_(None)))
            rows = (await s.execute(q)).scalars().all()
            return [
                {
                    "id": str(p.id),
                    "goal_id": str(p.goal_id) if p.goal_id else None,
                    "family": p.family,
                    "params": p.params,
                    "enabled": p.enabled,
                }
                for p in rows
            ]

    async def get(self, goal_id: str) -> dict[str, Any]:
        async with self._sf() as s:
            g = await self._get(s, goal_id)
            steps = (
                await s.execute(
                    select(StepRow).where(StepRow.goal_id == g.id).order_by(StepRow.seq)
                )
            ).scalars().all()
            facts = (
                await s.execute(
                    select(FactRow).where(FactRow.goal_id == g.id).order_by(FactRow.key)
                )
            ).scalars().all()
            events = (
                await s.execute(
                    select(EventRow)
                    .where(EventRow.goal_id == g.id)
                    .order_by(EventRow.created_at.desc())
                    .limit(20)
                )
            ).scalars().all()
            out = _goal_dict(g)
            out["steps"] = [_step_dict(x) for x in steps]
            out["facts"] = [_fact_dict(x) for x in facts]
            out["recent_events"] = [
                {"kind": e.kind, "payload": e.payload, "at": e.created_at.isoformat()}
                for e in events
            ]
            return out

    async def list(
        self, *, stage: str | None = None, include_closed: bool = False
    ) -> list[dict[str, Any]]:
        async with self._sf() as s:
            q = select(GoalRow).order_by(GoalRow.created_at)
            if stage:
                q = q.where(GoalRow.stage == stage)
            elif not include_closed:
                q = q.where(GoalRow.stage != "closed")
            rows = (await s.execute(q)).scalars().all()
            return [_goal_dict(g) for g in rows]

    async def update(
        self,
        goal_id: str,
        *,
        statement: str | None = None,
        definition_of_done: str | None = None,
        deadline: str | None = None,
        stage: str | None = None,
        note: str | None = None,
        cadence: str | None = None,
    ) -> dict[str, Any]:
        async with self._sf() as s:
            g = await self._get(s, goal_id)
            if is_terminal(g.stage):
                raise ValueError("goal is closed — closed goals cannot be changed")
            changed: dict[str, Any] = {}
            if statement is not None and statement.strip():
                g.statement = statement.strip()
                changed["statement"] = g.statement
            if definition_of_done is not None and definition_of_done.strip():
                g.definition_of_done = definition_of_done.strip()
                changed["definition_of_done"] = g.definition_of_done
            if deadline is not None:
                g.deadline = _parse_deadline(deadline)
                changed["deadline"] = deadline
            if cadence is not None:
                g.cadence = cadence.strip() or None
                changed["cadence"] = g.cadence
            if stage is not None and stage != g.stage:
                if stage == "closed":
                    raise ValueError("use goal_close to close a goal (an outcome is required)")
                if not can_transition(g.stage, stage):
                    raise ValueError(f"cannot move a goal from {g.stage!r} to {stage!r}")
                if stage == "active":
                    cap = await self._cap()
                    active_count = len(
                        (
                            await s.execute(select(GoalRow).where(GoalRow.stage == "active"))
                        ).scalars().all()
                    )
                    if active_count >= cap:
                        raise ValueError(
                            f"active-goal cap ({cap}) reached — close or "
                            "park another goal first, then activate this one"
                        )
                # owner ratification of an agent-proposed goal
                if g.stage == "proposed" and stage == "active" and g.approved_at is None:
                    g.approved_at = datetime.now(UTC)
                    self._event(s, g.id, "approved", {})
                self._event(s, g.id, "stage_change", {"from": g.stage, "to": stage})
                g.stage = stage
                changed["stage"] = stage
            if note is not None and note.strip():
                self._event(s, g.id, "note", {"text": note.strip()})
                changed["note"] = note.strip()
            if changed and set(changed) - {"note"}:
                self._event(s, g.id, "updated", {k: v for k, v in changed.items() if k != "note"})
            await s.commit()
            return _goal_dict(g)

    # -- steps ---------------------------------------------------------------

    async def step_add(self, goal_id: str, title: str, *, note: str = "") -> dict[str, Any]:
        if not (title or "").strip():
            raise ValueError("step title must be non-empty")
        async with self._sf() as s:
            g = await self._get(s, goal_id)
            if is_terminal(g.stage):
                raise ValueError("goal is closed — closed goals cannot be changed")
            max_seq = max(
                (
                    r.seq
                    for r in (
                        await s.execute(select(StepRow).where(StepRow.goal_id == g.id))
                    ).scalars()
                ),
                default=-1,
            )
            step = StepRow(goal_id=g.id, seq=max_seq + 1, title=title.strip(), note=note)
            s.add(step)
            await s.flush()
            self._event(s, g.id, "step_change", {"op": "add", "step_id": str(step.id), "title": step.title})
            await s.commit()
            return _step_dict(step)

    async def step_set_status(
        self, goal_id: str, step_id: str, status: str, *, note: str = ""
    ) -> dict[str, Any]:
        if status not in ("planned", "active", "done", "ghost"):
            raise ValueError("step status must be planned | active | done | ghost")
        async with self._sf() as s:
            g = await self._get(s, goal_id)
            if is_terminal(g.stage):
                raise ValueError("goal is closed — closed goals cannot be changed")
            step = await s.get(StepRow, _uuid_of(step_id))
            if step is None or step.goal_id != g.id:
                raise LookupError(f"no step {step_id} on goal {goal_id}")
            step.status = status
            if note:
                step.note = note
            self._event(
                s, g.id, "step_change",
                {"op": status, "step_id": str(step.id), "title": step.title},
            )
            await s.commit()
            return _step_dict(step)

    # -- facts ---------------------------------------------------------------

    async def fact_set(
        self, goal_id: str, key: str, value: Any, *, source: str = ""
    ) -> dict[str, Any]:
        if not (key or "").strip():
            raise ValueError("fact key must be non-empty")
        async with self._sf() as s:
            g = await self._get(s, goal_id)
            if is_terminal(g.stage):
                raise ValueError("goal is closed — closed goals cannot be changed")
            existing = (
                await s.execute(
                    select(FactRow).where(FactRow.goal_id == g.id, FactRow.key == key.strip())
                )
            ).scalar_one_or_none()
            if existing is not None and existing.authority in ("human", "system"):
                raise ValueError(
                    f"fact {key!r} has authority {existing.authority!r} — the agent may "
                    "propose a new value in a note, not overwrite it"
                )
            if existing is None:
                existing = FactRow(goal_id=g.id, key=key.strip(), value={"v": value}, source=source)
                s.add(existing)
            else:
                existing.value = {"v": value}
                existing.source = source or existing.source
            self._event(s, g.id, "fact_set", {"key": key.strip(), "value": value, "source": source})
            await s.commit()
            return _fact_dict(existing)

    # -- close ---------------------------------------------------------------

    async def close(
        self,
        goal_id: str,
        *,
        outcome: str,
        outcome_label: str | None = None,
        reason: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._sf() as s:
            g = await self._get(s, goal_id)
            err = validate_close(
                stage=g.stage,
                outcome=outcome,
                outcome_label=outcome_label,
                outcome_labels=g.outcome_labels or {},
                reason=reason,
            )
            if err:
                raise ValueError(err)
            self._event(s, g.id, "stage_change", {"from": g.stage, "to": "closed"})
            g.stage = "closed"
            g.outcome = outcome
            g.outcome_label = outcome_label
            g.outcome_reason = reason
            self._event(
                s, g.id, "closed",
                {"outcome": outcome, "outcome_label": outcome_label, "reason": reason},
            )
            await s.commit()
            return _goal_dict(g)


# ---------------------------------------------------------------------------
# Tool handler factories — bound to a store, registered by __init__.on_load.
# ---------------------------------------------------------------------------


def _normalize_labels(outcome_labels: Any) -> dict[str, str] | None:
    """Accept both shapes: {label: outcome} and [{label, outcome}] (the tool
    schema uses the array form because strict providers reject free-key
    objects). Bad entries pass through so validate_open reports them."""
    if outcome_labels is None or isinstance(outcome_labels, dict):
        return outcome_labels
    if isinstance(outcome_labels, list):
        out: dict[str, str] = {}
        for item in outcome_labels:
            if isinstance(item, dict) and "label" in item:
                out[str(item["label"])] = str(item.get("outcome", ""))
        return out
    return outcome_labels  # let validation produce the error message


def _normalize_reason(reason: Any) -> Any:
    """A sloppy model sends reason as a plain string — keep the structured
    contract by wrapping it as the summary."""
    if isinstance(reason, str) and reason.strip():
        return {"summary": reason.strip()}
    return reason


def make_handlers(
    store: GoalseekStore,
    *,
    effects=None,
    grant_store=None,
    approvals=None,
    waits=None,
    runtime=None,
    knowledge=None,
) -> dict[str, Any]:
    """Phase 01 handlers + phase 02 (goal_effect / goal_policy_set /
    goal_grant_revoke) + phase 03 (goal_wait / goal_wait_resolve) + phase 06
    (goal_note + wiki write-throughs). All later-phase dependencies are
    optional so earlier tests keep working with just a store. ``runtime``
    (phase 03) carries trigger sync; ``knowledge`` (phase 06) carries the
    wiki seam — both feature detected, never required."""

    async def _sync(goal_id: str) -> str | None:
        if runtime is None:
            return None
        try:
            return await runtime.sync(goal_id)
        except Exception as e:  # noqa: BLE001 — sync must never break a mutation
            import logging

            logging.getLogger("plugin-goalseek").warning("trigger sync failed: %s", e)
            return None

    async def _knowledge(method: str, *args: Any) -> None:
        """Best-effort wiki write-through — a wiki outage must never fail a
        goal mutation (the DB row is the source of truth either way)."""
        if knowledge is None:
            return
        try:
            await getattr(knowledge, method)(*args)
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger("plugin-goalseek").warning(
                "knowledge %s failed: %s", method, e
            )

    async def goal_open(
        statement: str,
        definition_of_done: str,
        deadline: str | None = None,
        autonomy_level: int | None = None,
        risk_ceiling: str = "medium",
        outcome_labels: Any = None,
        steps: list | None = None,
        opened_by: str = "owner",
        cadence: str | None = None,
        **_extra: Any,
    ) -> dict:
        opened_by = opened_by if opened_by in ("owner", "agent") else "owner"
        if autonomy_level is None:
            # Phase 05: the owner's default_autonomy_level setting applies
            # when the caller doesn't say otherwise.
            autonomy_level = await store.default_autonomy()
        approved_via: str | None = None
        if opened_by == "agent":
            # Persistent grant → silent open. Otherwise raise the approval card
            # ("approve always" on the card writes the grant for next time).
            # No approvals engine (tests / degraded boot) → park as proposed.
            from .grants import AUTO_APPROVE_AGENT_GOALS

            if grant_store is not None and await grant_store.is_active(AUTO_APPROVE_AGENT_GOALS):
                approved_via = "grant:auto_approve_agent_goals"
            elif approvals is not None:
                decision = await approvals.request(
                    kind="tool_call",
                    summary=f"Luna wants to open a goal: {str(statement)[:120]}",
                    payload={
                        "tool": "goal_open",
                        "args": {"statement": statement, "definition_of_done": definition_of_done},
                        "goalseek": {"self_opened": True},
                    },
                    requested_by_plugin="plugin-goalseek",
                    risk_level="medium",
                    plugin="plugin-goalseek",
                )
                if decision.decision != "approved":
                    return {
                        "status": "rejected",
                        "reason": decision.reason or "owner rejected opening this goal",
                    }
                approved_via = "approval_card"
                if grant_store is not None and getattr(decision, "lifetime", "once") == "always":
                    await grant_store.grant(AUTO_APPROVE_AGENT_GOALS)
        out = await store.open(
            statement=statement,
            definition_of_done=definition_of_done,
            deadline=deadline,
            autonomy_level=autonomy_level,
            risk_ceiling=risk_ceiling,
            outcome_labels=_normalize_labels(outcome_labels),
            steps=steps,
            opened_by=opened_by,
            approved_via=approved_via,
            cadence=cadence,
        )
        sync = await _sync(out["id"])
        if sync:
            out["schedules"] = sync
        await _knowledge("on_goal_open", out)
        return out

    async def goal_get(goal_id: str, **_extra: Any) -> dict:
        return await store.get(goal_id)

    async def goal_list(
        stage: str | None = None, include_closed: bool = False, **_extra: Any
    ) -> dict:
        goals = await store.list(stage=stage, include_closed=bool(include_closed))
        return {"goals": goals, "count": len(goals)}

    async def goal_update(
        goal_id: str,
        statement: str | None = None,
        definition_of_done: str | None = None,
        deadline: str | None = None,
        stage: str | None = None,
        note: str | None = None,
        step_add: str | None = None,
        step_id: str | None = None,
        step_status: str | None = None,
        cadence: str | None = None,
        **_extra: Any,
    ) -> dict:
        if _extra and ("outcome" in _extra or "outcome_label" in _extra):
            raise ValueError(
                "goal_update cannot close a goal — call goal_close with "
                "outcome, optional outcome_label and a reason {summary}"
            )
        out = await store.update(
            goal_id,
            statement=statement,
            definition_of_done=definition_of_done,
            deadline=deadline,
            stage=stage,
            note=note,
            cadence=cadence,
        )
        if step_add:
            out.setdefault("steps_changed", []).append(
                await store.step_add(goal_id, step_add)
            )
        if step_id and step_status:
            out.setdefault("steps_changed", []).append(
                await store.step_set_status(goal_id, step_id, step_status)
            )
        if stage is not None or deadline is not None or cadence is not None:
            sync = await _sync(goal_id)
            if sync:
                out["schedules"] = sync
        return out

    async def goal_fact_set(
        goal_id: str, key: str, value=None, source: str = "", **_extra: Any
    ) -> dict:
        out = await store.fact_set(goal_id, key, value, source=source)
        # Phase 03: a fact write may resolve fact_present waits on this goal.
        if waits is not None:
            resolved = await waits.resolve_fact_present(goal_id, str(key).strip())
            if resolved:
                out["waits_resolved"] = resolved
                await _sync(goal_id)
        # Phase 06: a namespaced fact (contact-jane/working_hours) also lands
        # on its domain wiki page — the compounding step.
        await _knowledge("on_fact_set", {"id": goal_id}, key, value, source)
        return out

    async def goal_close(
        goal_id: str,
        outcome: str,
        outcome_label: str | None = None,
        reason: Any = None,
        **_extra: Any,
    ) -> dict:
        out = await store.close(
            goal_id,
            outcome=outcome,
            outcome_label=outcome_label,
            reason=_normalize_reason(reason),
        )
        await _sync(goal_id)
        await _knowledge("on_goal_close", out)
        return out

    async def goal_effect(
        goal_id: str,
        intent: str,
        tool: str | None = None,
        args: Any = None,
        kind: str = "tool_call",
        playbook: str | None = None,
        risk: str = "medium",
        contact: str | None = None,
        channel: str | None = None,
        target: str | None = None,
        is_write: bool = False,
        writes_fact: str | None = None,
        **_extra: Any,
    ) -> dict:
        if effects is None:
            raise RuntimeError("effects bridge not wired — goal_effect unavailable")
        if isinstance(args, str):
            import json as _json

            try:
                args = _json.loads(args) if args.strip() else {}
            except ValueError:
                raise ValueError("args must be a JSON object (got unparseable text)") from None
        # Infer the kind when the model passes a playbook without kind.
        if playbook and kind == "tool_call" and not tool:
            kind = "playbook_run"
        if kind not in ("tool_call", "playbook_run"):
            kind = "tool_call"
        if kind == "tool_call" and not tool:
            raise ValueError("kind='tool_call' needs 'tool' (the tool name to execute)")
        return await effects.run(
            goal_id=goal_id,
            kind=kind,
            tool=tool or "",
            args=args or {},
            intent=intent,
            risk=risk if risk in ("low", "medium", "high") else "medium",
            contact=contact,
            channel=channel,
            target=target,
            is_write=bool(is_write),
            writes_fact=writes_fact,
            playbook=playbook,
        )

    async def goal_policy_set(
        family: str,
        params: Any = None,
        goal_id: str | None = None,
        enabled: bool = True,
        **_extra: Any,
    ) -> dict:
        if isinstance(params, str):
            import json as _json

            try:
                params = _json.loads(params) if params.strip() else {}
            except ValueError:
                raise ValueError("params must be a JSON object (got unparseable text)") from None
        return await store.policy_set(
            family=family,
            params=params or {},
            goal_id=goal_id,
            enabled=bool(enabled),
        )

    async def goal_grant_revoke(key: str, **_extra: Any) -> dict:
        if grant_store is None:
            raise RuntimeError("grant store not wired — goal_grant_revoke unavailable")
        return await grant_store.revoke(key)

    async def goal_wait(
        goal_id: str,
        description: str,
        kind: str,
        until: str | None = None,
        fact_key: str | None = None,
        timeout: str | None = None,
        keep_heartbeat: bool = False,
        **_extra: Any,
    ) -> dict:
        if waits is None:
            raise RuntimeError("waits store not wired — goal_wait unavailable")
        conversation_id = None
        if runtime is not None:
            conversation_id = runtime.current_conversation_id()
        out = await waits.open(
            goal_id=goal_id,
            description=description,
            kind=kind,
            until=until,
            fact_key=fact_key,
            timeout=timeout,
            keep_heartbeat=bool(keep_heartbeat),
            conversation_id=conversation_id,
        )
        if kind == "until_time" and runtime is not None:
            out["trigger"] = await runtime.create_until_trigger(goal_id, out)
        await _sync(goal_id)
        return out

    async def goal_note(
        goal_id: str, title: str, body_md: str, **_extra: Any
    ) -> dict:
        if knowledge is None:
            raise RuntimeError("knowledge seam not wired — goal_note unavailable")
        if not (title or "").strip() or not (body_md or "").strip():
            raise ValueError("goal_note needs a non-empty title and body_md")
        goal = await store.get(goal_id)  # LookupError when missing
        if is_terminal(goal["stage"]):
            raise ValueError("goal is closed — closed goals cannot be changed")
        out = await knowledge.write_note(goal, title.strip(), body_md)
        # The evidence trail records that (and where) the note landed.
        async with store._sf() as s:  # noqa: SLF001 — same-module seam
            store._event(
                s, _uuid_of(goal_id), "note",
                {"text": title.strip(), "knowledge": out},
            )
            await s.commit()
        return {"status": "written", **out}

    async def goal_wait_resolve(
        wait_id: str, note: str = "", cancel: bool = False, **_extra: Any
    ) -> dict:
        if waits is None:
            raise RuntimeError("waits store not wired — goal_wait_resolve unavailable")
        out = (
            await waits.cancel(wait_id, note=note)
            if cancel
            else await waits.resolve(wait_id, note=note)
        )
        if runtime is not None:
            await runtime.delete_until_trigger(out["goal_id"], wait_id)
        await _sync(out["goal_id"])
        return out

    return {
        "goal_open": goal_open,
        "goal_get": goal_get,
        "goal_list": goal_list,
        "goal_update": goal_update,
        "goal_fact_set": goal_fact_set,
        "goal_close": goal_close,
        "goal_effect": goal_effect,
        "goal_policy_set": goal_policy_set,
        "goal_grant_revoke": goal_grant_revoke,
        "goal_wait": goal_wait,
        "goal_wait_resolve": goal_wait_resolve,
        "goal_note": goal_note,
    }
