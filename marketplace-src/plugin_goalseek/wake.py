"""Scheduler-driven wakes: heartbeat triggers, deadline one-shots, and the
muted resume path.

The curiosity pattern, made per-goal: call plugin-scheduler's tool handlers
DIRECTLY through the registry (all involved tools are auto_approve), never via
chat. Everything feature-detects — no scheduler installed means goals simply
don't self-wake (they still work in chat), and the sync reports why.

Trigger topology per goal:

- ``goalseek-hb-<id8>``  — the recurring heartbeat (goal cadence, default
  daily 09:30). Exists only while the goal is ``active``; paused when the
  goal is waiting/parked; deleted when closed.
- ``goalseek-dl-<id8>``  — a one-shot at the goal's deadline (yearly cron
  pinned to day+month, ``max_runs=1``) that forces a closing review.
- ``goalseek-ut-<id8>-<w8>`` — a one-shot for an ``until_time`` wait.

The wake prompt is the discipline: one most-valuable step through
``goal_effect``, update the plan, stop. Budget ≤8 tool calls (prompt-enforced
in v1 — see the phase plan).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger("plugin-goalseek.wake")

DEFAULT_CADENCE = "every day at 09:30"

# Minimum gap between muted wakes for one goal (re-entrancy guard).
WAKE_GUARD_MINUTES = 5


def heartbeat_name(goal_id: str) -> str:
    return f"goalseek-hb-{str(goal_id)[:8]}"


def deadline_name(goal_id: str) -> str:
    return f"goalseek-dl-{str(goal_id)[:8]}"


def until_name(goal_id: str, wait_id: str) -> str:
    return f"goalseek-ut-{str(goal_id)[:8]}-{str(wait_id)[:8]}"


def one_shot_cron(at: datetime) -> str:
    """A 5-field cron pinned to minute/hour/day/month — fires at the next
    occurrence of that wall-clock instant (within a year), and ``max_runs=1``
    makes it a one-shot. The scheduler grammar has no absolute-datetime form."""
    return f"{at.minute} {at.hour} {at.day} {at.month} *"


def wake_prompt(goal: dict[str, Any], *, reason: str = "heartbeat",
                waits: list[dict] | None = None, reflection: str | None = None) -> str:
    lines = [
        f"Goal-seek wake ({reason}) for goal {goal['id']} — \"{goal['statement']}\".",
        f"Definition of done: {goal['definition_of_done']}. Stage: {goal['stage']}.",
    ]
    if goal.get("deadline"):
        lines.append(f"Deadline: {goal['deadline']}.")
    open_waits = [w for w in (waits or []) if w.get("status") == "open"]
    if open_waits:
        described = "; ".join(w["description"] for w in open_waits[:3])
        lines.append(f"Open waits: {described}.")
    if reflection:
        lines.append(f"Tuning: {reflection.splitlines()[0]}")
    lines.append(
        "Do the single most valuable next step for this goal now: goal_get "
        "first, act through goal_effect (follow any remedy it returns), then "
        "goal_update with progress and stop. If nothing can progress, set a "
        "goal_wait and stop. If the definition of done is met (or the deadline "
        "passed), run a closing review and goal_close with an honest outcome. "
        "Budget: at most 8 tool calls."
    )
    return "\n".join(lines)


def deadline_prompt(goal: dict[str, Any]) -> str:
    return (
        f"Goal-seek deadline reached for goal {goal['id']} — \"{goal['statement']}\".\n"
        f"Definition of done: {goal['definition_of_done']}.\n"
        "Run the closing review now: goal_get, judge honestly whether the "
        "definition of done is met, then goal_close with outcome 'achieved' or "
        "'expired' (with a structured reason). If a short extension is clearly "
        "justified, goal_update the deadline instead and say why. "
        "Budget: at most 8 tool calls."
    )


class TriggerSync:
    """Idempotent trigger lifecycle for goals, bound to a tool registry.

    ``registry.get(name).handler`` is the only surface used, so tests inject a
    fake. Every method degrades to a string report — sync failures must never
    break a goal mutation.
    """

    def __init__(self, tool_registry) -> None:
        self._registry = tool_registry

    def _handler(self, name: str):
        if self._registry is None:
            return None
        try:
            return self._registry.get(name).handler
        except (KeyError, AttributeError):
            return None

    async def _existing(self) -> dict[str, dict] | None:
        lister = self._handler("trigger_list")
        if lister is None:
            return None
        try:
            listed = await lister()
        except Exception as e:  # noqa: BLE001
            log.warning("trigger_list failed: %s", e)
            return None
        if "error" in listed:
            log.warning("trigger_list error: %s", listed["error"])
            return None
        return {t.get("name"): t for t in listed.get("triggers", [])}

    async def sync_goal(self, goal: dict[str, Any], *,
                        waits: list[dict] | None = None,
                        reflection: str | None = None) -> str:
        """Bring this goal's triggers in line with its stage. Idempotent."""
        creator = self._handler("trigger_create")
        if creator is None:
            return "plugin-scheduler not installed — goal will not self-wake"
        existing = await self._existing()
        if existing is None:
            return "scheduler unreachable — trigger sync skipped"

        gid = goal["id"]
        hb = heartbeat_name(gid)
        dl = deadline_name(gid)
        actions: list[str] = []

        if goal["stage"] == "active":
            # Heartbeat: unique_name upserts target/schedule drift in place.
            result = await creator(
                name=hb,
                schedule_expr=goal.get("cadence") or DEFAULT_CADENCE,
                action_type="agent_prompt",
                target=wake_prompt(goal, waits=waits, reflection=reflection),
                purpose=f"goal-seek heartbeat: {goal['statement'][:60]}",
                unique_name=True,
            )
            if "error" in result:
                return f"trigger_create({hb}) failed: {result['error']}"
            actions.append(f"heartbeat {'created' if hb not in existing else 'synced'}")
            if hb in existing and not existing[hb].get("enabled", True):
                resumer = self._handler("trigger_resume")
                if resumer is not None:
                    await resumer(id=existing[hb]["id"])
                    actions.append("heartbeat resumed")
            # Deadline one-shot.
            if goal.get("deadline"):
                deadline = datetime.fromisoformat(goal["deadline"])
                if deadline > datetime.now(UTC):
                    result = await creator(
                        name=dl,
                        schedule_expr=one_shot_cron(deadline),
                        action_type="agent_prompt",
                        target=deadline_prompt(goal),
                        purpose=f"goal-seek deadline review: {goal['statement'][:50]}",
                        unique_name=True,
                        max_runs=1,
                    )
                    if "error" not in result:
                        actions.append("deadline one-shot synced")
            elif dl in existing:
                await self._delete(existing[dl]["id"])
                actions.append("stale deadline trigger deleted")
        elif goal["stage"] in ("waiting", "parked", "proposed", "closing"):
            keep = any(w.get("keep_heartbeat") for w in (waits or []) if w.get("status") == "open")
            if hb in existing and existing[hb].get("enabled", True) and not keep:
                pauser = self._handler("trigger_pause")
                if pauser is not None:
                    await pauser(id=existing[hb]["id"])
                    actions.append("heartbeat paused")
        elif goal["stage"] == "closed":
            for name in (hb, dl):
                if name in existing:
                    await self._delete(existing[name]["id"])
                    actions.append(f"{name} deleted")
            # Sweep any until-time one-shots left behind.
            prefix = f"goalseek-ut-{str(gid)[:8]}-"
            for name, t in existing.items():
                if name and name.startswith(prefix):
                    await self._delete(t["id"])
                    actions.append(f"{name} deleted")
        return "; ".join(actions) if actions else "no trigger changes"

    async def create_until_time(self, goal: dict[str, Any], wait_id: str,
                                until: datetime) -> str:
        creator = self._handler("trigger_create")
        if creator is None:
            return "plugin-scheduler not installed"
        name = until_name(goal["id"], wait_id)
        result = await creator(
            name=name,
            schedule_expr=one_shot_cron(until),
            action_type="agent_prompt",
            target=(
                f"Goal-seek wait {wait_id} on goal {goal['id']} "
                f"(\"{goal['statement'][:60]}\") has come due. Call "
                f"goal_wait_resolve(wait_id='{wait_id}') and then continue the "
                "goal: one most-valuable step via goal_effect, goal_update, stop. "
                "Budget: at most 8 tool calls."
            ),
            purpose=f"goal-seek until-time wait: {goal['statement'][:50]}",
            unique_name=True,
            max_runs=1,
        )
        return f"error: {result['error']}" if "error" in result else "created"

    async def delete_until_time(self, goal_id: str, wait_id: str) -> None:
        existing = await self._existing()
        if not existing:
            return
        t = existing.get(until_name(goal_id, wait_id))
        if t is not None:
            await self._delete(t["id"])

    async def _delete(self, trigger_id: Any) -> None:
        deleter = self._handler("trigger_delete")
        if deleter is None:
            return
        try:
            await deleter(id=trigger_id)
        except Exception as e:  # noqa: BLE001
            log.warning("trigger_delete(%s) failed: %s", trigger_id, e)


def recently_woken(recent_events: list[dict], now: datetime,
                   *, minutes: int = WAKE_GUARD_MINUTES) -> bool:
    """Re-entrancy guard over the goal's event trail: True when a muted wake
    was already sent inside the window (events newest-first, ``at`` datetime
    or iso string)."""
    cutoff = now - timedelta(minutes=minutes)
    for e in recent_events:
        if e.get("kind") != "wake_sent":
            continue
        at = e.get("at")
        if isinstance(at, str):
            try:
                at = datetime.fromisoformat(at)
            except ValueError:
                continue
        if isinstance(at, datetime):
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            return at >= cutoff
    return False


class GoalseekRuntime:
    """Phase-03 orchestration bound to the live PluginContext: trigger sync,
    the turn-ended resume path, and muted wakes. Injected into make_handlers
    as ``runtime`` — everything here is best-effort and never raises into a
    tool call."""

    def __init__(self, ctx, store, waits) -> None:
        self._ctx = ctx
        self._store = store
        self._waits = waits
        self._sync = TriggerSync(getattr(ctx, "tool_registry", None))
        self._wake_task = None

    # -- surface used by tools.make_handlers -----------------------------------

    def current_conversation_id(self) -> str | None:
        cid = getattr(self._ctx, "current_conversation_id", None)
        return str(cid) if cid else None

    async def sync(self, goal_id: str) -> str:
        goal = await self._store.get(goal_id)
        waits = await self._waits.list_open(goal_id)
        return await self._sync.sync_goal(goal, waits=waits)

    async def sync_all(self) -> str:
        """on_load repair: bring every non-closed goal's triggers in line
        (recreates triggers a dead scheduler lost, pauses waiting goals)."""
        reports = []
        for g in await self._store.list(include_closed=False):
            try:
                reports.append(f"{str(g['id'])[:8]}: {await self.sync(g['id'])}")
            except Exception as e:  # noqa: BLE001
                reports.append(f"{str(g['id'])[:8]}: sync failed ({e})")
        return "; ".join(reports) if reports else "no live goals"

    async def create_until_trigger(self, goal_id: str, wait: dict) -> str:
        goal = await self._store.get(goal_id)
        until = datetime.fromisoformat(wait["params"]["until"])
        return await self._sync.create_until_time(goal, wait["id"], until)

    async def delete_until_trigger(self, goal_id: str, wait_id: str) -> None:
        try:
            await self._sync.delete_until_time(goal_id, wait_id)
        except Exception as e:  # noqa: BLE001
            log.warning("until-trigger cleanup failed: %s", e)

    # -- the event-resume path ---------------------------------------------------

    async def on_turn_ended(self, payload: dict) -> None:
        """agent.turn.ended handler. Owner chat turns may resolve owner_reply
        waits; every turn end is also a cheap moment to sweep due/timed-out
        waits. Resolved waits wake their goal with ONE muted turn each,
        guarded against repeats. The wakes are spawned fire-and-forget —
        ``emit`` awaits its handlers, so running a whole muted turn inline
        would nest it inside the ending turn's finalization."""
        try:
            source = payload.get("source")
            conversation_id = payload.get("conversation_id")
            resolved: list[dict] = []
            if source == "chat":
                resolved.extend(await self._waits.resolve_owner_reply(conversation_id))
            swept = await self._waits.sweep_due()
            resolved.extend(swept["met"])
            resolved.extend(swept["timed_out"])
            if resolved:
                import asyncio

                # Kept on self so tests (and shutdown) can await the last one.
                self._wake_task = asyncio.get_running_loop().create_task(
                    self._wake_resolved(resolved)
                )
        except Exception as e:  # noqa: BLE001 — a handler crash must not hurt the bus
            log.warning("turn-ended handling failed: %s", e)

    async def _wake_resolved(self, resolved: list[dict]) -> None:
        for wait in resolved:
            try:
                await self._wake_goal(wait["goal_id"],
                                      reason=f"wait resolved: {wait['description'][:60]}")
            except Exception as e:  # noqa: BLE001
                log.warning("wake for goal %s failed: %s", wait.get("goal_id"), e)

    async def _wake_goal(self, goal_id: str, *, reason: str) -> None:
        goal = await self._store.get(goal_id)
        if goal["stage"] not in ("active", "waiting"):
            await self.sync(goal_id)
            return
        events = goal.get("recent_events") or []
        if recently_woken(events, datetime.now(UTC)):
            log.info("wake guard: goal %s woken < %d min ago — skipping",
                     goal_id, WAKE_GUARD_MINUTES)
            return
        send = getattr(self._ctx, "send_muted_message", None)
        if not callable(send):
            return
        await self._record_wake(goal_id, reason)
        with billing_scope(goal_id):
            await send(
                title=f"Goal resumed: {goal['statement'][:40]}",
                content=wake_prompt(goal, reason=reason,
                                    waits=await self._waits.list_open(goal_id)),
                channel="moment",
                tools="all",
            )
        await self.sync(goal_id)

    async def _record_wake(self, goal_id: str, reason: str) -> None:
        import uuid as _uuid

        from .models import EventRow

        sf = getattr(self._store, "_sf")  # noqa: B009 — same-package access
        async with sf() as s:
            s.add(EventRow(goal_id=_uuid.UUID(str(goal_id)), kind="wake_sent",
                           payload={"reason": reason}))
            await s.commit()


def billing_scope(goal_id: str):
    """The billing origin for a goalseek-initiated muted wake. Reuses the
    allowlisted ``scheduled_run`` type until phase 08 adds ``goalseek_run``
    (then: change ROOT_ACTION_TYPE, one constant). No-op on older cores."""
    from contextlib import nullcontext

    try:
        from luna_sdk import billing_origin_scope
    except Exception:  # noqa: BLE001 — older core: degrade to no attribution
        return nullcontext()
    return billing_origin_scope(
        channel="scheduler",
        root_action_type=ROOT_ACTION_TYPE,
        job_id=f"goalseek-{goal_id}",
    )


ROOT_ACTION_TYPE = "scheduled_run"
