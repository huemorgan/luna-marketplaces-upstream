"""goal_effect — the one governed door between a goal and the world.

Flow: record ``effect_requested`` → policy gate → (block | approval card |
execute). Execution appends ``effect_confirmed`` only with real result
evidence (summary + hash); failures append ``effect_failed``. Blocks append
``policy_block`` with the family, reason and remedy and NEVER raise — the
agent must read the remedy, that is the self-tuning contract.

Design rule (lint-tested): no other goalseek code path calls foreign tools.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from . import policy as policy_mod
from . import tuning
from .models import EventRow, FactRow, GoalRow, PolicyRow

log = logging.getLogger("plugin-goalseek.effects")

# The identical call repeated inside this window counts as a duplicate
# (the practical stand-in for "one turn" — plugins don't see turn boundaries).
DUPLICATE_WINDOW_MINUTES = 10

RECENT_EVENTS_FOR_GATE = 100

# Phase 04: how long a goal_effect call waits inline for a playbook run.
# playbook_run executes synchronously (runner awaits every step before
# returning), so most runs finish well inside this. Past the budget the run
# keeps going in the background and the goal parks on a wait.
PLAYBOOK_BUDGET_S = 90.0

# Safety net if the process dies mid-run: the parked wait times out and the
# sweep wakes the goal to reassess (the run itself died with the process).
PLAYBOOK_WAIT_TIMEOUT_HOURS = 6


def _result_evidence(result: Any) -> dict[str, Any]:
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    return {
        "result_summary": text[:400],
        "result_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "result_bytes": len(text.encode()),
    }


class EffectsBridge:
    """Bound to the goalseek store's session factory + the live tool registry."""

    def __init__(self, session_factory, tool_registry=None, approvals=None,
                 plugin_name: str = "plugin-goalseek", waits=None, runtime=None,
                 settings=None, knowledge=None) -> None:
        self._sf = session_factory
        self._tools = tool_registry
        self._approvals = approvals
        self._plugin = plugin_name
        # Phase 04: WaitStore + GoalseekRuntime, for parking on long playbook
        # runs and waking when the background run lands. Both optional.
        self._waits = waits
        self._runtime = runtime
        # Phase 05: SettingsStore — quiet_hours becomes a synthetic global
        # timing policy at gate time (single source: the owner setting).
        self._settings = settings
        # Phase 06: the wiki seam — eligibility's requires_facts can satisfy
        # from a domain wiki page when the DB fact is missing.
        self._knowledge = knowledge
        # Kept so tests/shutdown can await in-flight background completions.
        self._bg_tasks: set[asyncio.Task] = set()

    # -- context assembly ----------------------------------------------------

    async def _gate_context(self, s, goal: GoalRow) -> dict[str, Any]:
        now = datetime.now(UTC)
        policies = (
            await s.execute(
                select(PolicyRow).where(
                    (PolicyRow.goal_id == goal.id) | (PolicyRow.goal_id.is_(None))
                )
            )
        ).scalars().all()
        facts = (
            await s.execute(select(FactRow).where(FactRow.goal_id == goal.id))
        ).scalars().all()
        events = (
            await s.execute(
                select(EventRow)
                .where(EventRow.goal_id == goal.id)
                .order_by(EventRow.created_at.desc())
                .limit(RECENT_EVENTS_FOR_GATE)
            )
        ).scalars().all()
        cutoff = now - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)

        policy_dicts = [
            {
                "goal_id": str(p.goal_id) if p.goal_id else None,
                "family": p.family,
                "params": p.params or {},
                "enabled": p.enabled,
            }
            for p in policies
        ]
        if self._settings is not None:
            try:
                quiet = await self._settings.get("quiet_hours")
            except Exception:  # noqa: BLE001
                quiet = None
            if quiet:
                policy_dicts.append({
                    "goal_id": None, "family": "timing",
                    "params": {"quiet_hours": str(quiet)}, "enabled": True,
                })

        def _aware(dt: datetime) -> datetime:
            # sqlite (tests) returns naive datetimes even for timezone=True columns
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        turn_keys = {
            (e.payload or {}).get("effect_key")
            for e in events
            if e.kind in ("effect_attempted", "effect_confirmed")
            and _aware(e.created_at) >= cutoff
            and (e.payload or {}).get("effect_key")
        }
        fact_dicts = {
            f.key: {"value": f.value, "authority": f.authority} for f in facts
        }
        # Phase 06: a required fact missing from the DB may live on a domain
        # wiki page (written by an earlier goal's tuning — the compounding
        # claim). Wiki-sourced values enter as agent authority; wiki failures
        # simply leave the gap and the eligibility block explains it.
        wiki_facts: list[str] = []
        if self._knowledge is not None:
            required: list[str] = []
            for p in policy_dicts:
                if p["family"] == "eligibility" and p.get("enabled", True):
                    required.extend((p.get("params") or {}).get("requires_facts") or [])
            for key in required:
                if key in fact_dicts:
                    continue
                try:
                    found = await self._knowledge.find_fact(key)
                except Exception:  # noqa: BLE001
                    found = None
                if found is not None:
                    fact_dicts[key] = found
                    wiki_facts.append(key)
        return {
            "now": now,
            "policies": policy_dicts,
            "facts": fact_dicts,
            # keys satisfied from wiki pages, not DB rows — surfaced in the
            # result so the agent can report WHY the gate passed (dojo: the
            # model guessed wrongly when this was invisible).
            "wiki_facts": wiki_facts,
            "recent_events": [
                {"kind": e.kind, "payload": e.payload, "at": _aware(e.created_at)}
                for e in events
            ],
            "turn_effect_keys": turn_keys,
        }

    @staticmethod
    def _goal_view(g: GoalRow) -> dict[str, Any]:
        return {
            "stage": g.stage,
            "outcome": g.outcome,
            "autonomy_level": g.autonomy_level,
            "risk_ceiling": g.risk_ceiling,
        }

    @staticmethod
    def _event(s, goal_id, kind: str, payload: dict | None = None) -> None:
        s.add(EventRow(goal_id=goal_id, kind=kind, payload=payload or {}))

    # -- the door --------------------------------------------------------------

    def _registered(self, tool_name: str):
        if self._tools is None:
            return None
        try:
            return self._tools.get(tool_name)
        except (KeyError, AttributeError):
            return None

    async def run(
        self,
        *,
        goal_id: str,
        kind: str,
        tool: str,
        args: dict[str, Any],
        intent: str,
        risk: str = "medium",
        contact: str | None = None,
        channel: str | None = None,
        target: str | None = None,
        is_write: bool = False,
        writes_fact: str | None = None,
        playbook: str | None = None,
    ) -> dict[str, Any]:
        import uuid as _uuid

        try:
            gid = _uuid.UUID(str(goal_id))
        except ValueError:
            raise LookupError(f"no goal with id {goal_id}") from None

        if kind == "playbook_run":
            # Feature-detected per call: installing/removing plugin-playbooks
            # needs no goalseek restart. Absent → the standard actionable
            # block shape, never an exception.
            if not playbook:
                raise ValueError("kind='playbook_run' needs 'playbook' (the playbook name)")
            if self._registered("playbook_run") is None:
                return {
                    "status": "blocked",
                    "family": "capability",
                    "reason": "plugin-playbooks not installed",
                    "remedy": "use kind='tool_call' steps instead, or install plugin-playbooks",
                }
            effect = {
                "kind": "playbook_run",
                # tool stays "playbook_run" so denied_tools + effect_key treat
                # playbook runs uniformly; the playbook name rides alongside.
                "payload": {"tool": "playbook_run", "playbook": playbook, "args": args},
                "intent": intent,
                "risk": risk,
                "contact": contact,
                "channel": channel,
                "target": target or playbook,
                "is_write": True,  # a playbook is a write-side effect by definition
                "writes_fact": writes_fact,
            }
            ekey = policy_mod.effect_key(effect)
            return await self._gate_then_execute(gid, effect, ekey)

        effect = {
            "kind": kind,
            "payload": {"tool": tool, "args": args},
            "intent": intent,
            "risk": risk,
            "contact": contact,
            "channel": channel,
            "target": target,
            "is_write": bool(is_write),
            "writes_fact": writes_fact,
        }
        ekey = policy_mod.effect_key(effect)
        return await self._gate_then_execute(gid, effect, ekey)

    async def _gate_then_execute(self, gid, effect, ekey) -> dict[str, Any]:
        kind = effect["kind"]
        tool = effect["payload"]["tool"]
        intent = effect["intent"]
        risk = effect.get("risk", "medium")

        async with self._sf() as s:
            goal = await s.get(GoalRow, gid)
            if goal is None:
                raise LookupError(f"no goal with id {gid}")

            self._event(
                s, goal.id, "effect_requested",
                {"intent": intent, "effect_kind": kind, "tool": tool,
                 "effect_key": ekey, "risk": risk},
            )
            context = await self._gate_context(s, goal)
            decision = policy_mod.evaluate(self._goal_view(goal), effect, context)

            if decision.kind == "block":
                stats = tuning.gate_stats(
                    [{"kind": e["kind"], "payload": e["payload"]} for e in context["recent_events"]]
                    + [{"kind": "policy_block", "payload": {"family": decision.family}}]
                )
                self._event(
                    s, goal.id, "policy_block",
                    {"family": decision.family, "reason": decision.reason,
                     "remedy": decision.remedy, "effect_key": ekey,
                     "attempted": {"kind": kind, "tool": tool, "intent": intent}},
                )
                await s.commit()
                out: dict[str, Any] = {
                    "status": "blocked",
                    "family": decision.family,
                    "reason": decision.reason,
                    "remedy": decision.remedy,
                }
                remedies = tuning.recent_remedies(
                    [{"kind": e["kind"], "payload": e["payload"]} for e in context["recent_events"]]
                )
                reflection = tuning.reflection_text(stats, [decision.remedy, *remedies])
                if reflection:
                    out["tuning_reflection"] = reflection
                return out

            if decision.kind == "needs_approval":
                await s.commit()
                return await self._run_with_approval(gid, effect, ekey, decision)

            # allow
            wiki_facts = context.get("wiki_facts") or []
            self._event(
                s, goal.id, "effect_attempted",
                {"effect_kind": kind, "tool": tool, "effect_key": ekey, "intent": intent,
                 **({"facts_from_wiki": wiki_facts} if wiki_facts else {})},
            )
            await s.commit()

        out = await self._execute(gid, effect, ekey)
        if wiki_facts and isinstance(out, dict):
            out["facts_from_wiki"] = wiki_facts
            out["note"] = (
                (out.get("note") or "")
                + f" Required facts {wiki_facts} were satisfied from the shared wiki "
                "(learned by an earlier goal), not from this goal's own facts."
            ).strip()
        return out

    async def _run_with_approval(self, gid, effect, ekey, decision) -> dict[str, Any]:
        if self._approvals is None:
            async with self._sf() as s:
                self._event(
                    s, gid, "effect_pending_approval",
                    {"effect_key": ekey, "intent": effect.get("intent")},
                )
                await s.commit()
            return {
                "status": "needs_approval",
                "reason": decision.reason,
                "note": "approval engine unavailable — the owner must act on this in chat",
            }
        approval = await self._approvals.request(
            kind="tool_call",
            summary=f"Goal effect: {effect.get('intent') or effect['payload']['tool']}",
            payload={
                "tool": effect["payload"]["tool"],
                "args": effect["payload"]["args"],
                "goalseek": {"goal_id": str(gid), "intent": effect.get("intent")},
            },
            requested_by_plugin=self._plugin,
            risk_level=effect.get("risk", "medium"),
            plugin=self._plugin,
        )
        if approval.decision != "approved":
            async with self._sf() as s:
                self._event(
                    s, gid, "effect_rejected",
                    {"effect_key": ekey, "reason": approval.reason or "owner rejected"},
                )
                await s.commit()
            return {
                "status": "rejected",
                "reason": approval.reason or "owner rejected this effect",
            }
        async with self._sf() as s:
            self._event(
                s, gid, "effect_attempted",
                {"effect_kind": effect["kind"], "tool": effect["payload"]["tool"],
                 "effect_key": ekey, "intent": effect.get("intent"), "approved": True},
            )
            await s.commit()
        return await self._execute(gid, effect, ekey)

    async def _execute(self, gid, effect, ekey) -> dict[str, Any]:
        if effect["kind"] == "playbook_run":
            return await self._execute_playbook(gid, effect, ekey)
        tool_name = effect["payload"]["tool"]
        args = effect["payload"]["args"] or {}
        registered = self._registered(tool_name)
        if registered is None:
            async with self._sf() as s:
                self._event(
                    s, gid, "effect_failed",
                    {"effect_key": ekey, "error": f"tool '{tool_name}' is not registered"},
                )
                await s.commit()
            return {
                "status": "failed",
                "error": f"tool '{tool_name}' is not registered — check the name with the tool list",
            }
        try:
            result = await registered.handler(**args)
        except Exception as e:  # noqa: BLE001 — the trail must record the failure
            async with self._sf() as s:
                self._event(
                    s, gid, "effect_failed",
                    {"effect_key": ekey, "error": f"{type(e).__name__}: {e}"},
                )
                await s.commit()
            return {"status": "failed", "error": f"{type(e).__name__}: {e}"}

        evidence = _result_evidence(result)
        async with self._sf() as s:
            self._event(
                s, gid, "effect_confirmed",
                {"effect_kind": effect["kind"], "tool": tool_name,
                 "effect_key": ekey, "target": effect.get("target"), **evidence},
            )
            await s.commit()
        return {"status": "done", "result": result, **evidence}

    # -- phase 04: playbook runs ------------------------------------------------

    async def _execute_playbook(self, gid, effect, ekey) -> dict[str, Any]:
        """Fire playbook_run through the registry. Runs are synchronous inside
        the handler, so we await up to PLAYBOOK_BUDGET_S; a longer run keeps
        going in the background while the goal parks on a wait that the
        completion callback resolves (waking the goal)."""
        name = effect["payload"]["playbook"]
        inputs = effect["payload"]["args"] or {}
        registered = self._registered("playbook_run")
        if registered is None:  # vanished between gate and execute
            return {
                "status": "blocked",
                "family": "capability",
                "reason": "plugin-playbooks not installed",
                "remedy": "use kind='tool_call' steps instead, or install plugin-playbooks",
            }

        task = asyncio.ensure_future(
            registered.handler(name=name, inputs=json.dumps(inputs))
        )
        done, pending = await asyncio.wait({task}, timeout=PLAYBOOK_BUDGET_S)
        if not pending:
            try:
                raw = task.result()
            except Exception as e:  # noqa: BLE001 — the trail must record it
                return await self._playbook_failed(gid, effect, ekey, f"{type(e).__name__}: {e}")
            return await self._record_playbook_result(gid, effect, ekey, raw)

        # Still running past the budget: never block the wake turn on it.
        wait_id = None
        if self._waits is not None:
            try:
                timeout_at = (
                    datetime.now(UTC) + timedelta(hours=PLAYBOOK_WAIT_TIMEOUT_HOURS)
                ).isoformat()
                w = await self._waits.open(
                    goal_id=str(gid),
                    description=f"playbook '{name}' is still running",
                    kind="manual",
                    timeout=timeout_at,
                )
                wait_id = w["id"]
            except Exception as e:  # noqa: BLE001
                log.warning("could not open playbook wait: %s", e)
        self._bg_tasks.add(task)
        task.add_done_callback(
            lambda t: self._spawn_finish(gid, effect, ekey, t, wait_id)
        )
        return {
            "status": "running",
            "note": (
                f"playbook '{name}' is still running in the background; the goal "
                "is parked on a wait and will wake when the run completes. Do "
                "NOT mark the step done."
            ),
            **({"wait_id": wait_id} if wait_id else {}),
        }

    def _spawn_finish(self, gid, effect, ekey, task, wait_id) -> None:
        self._bg_tasks.discard(task)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # loop is gone (shutdown) — the timeout sweep picks it up
        t = loop.create_task(self._finish_playbook_bg(gid, effect, ekey, task, wait_id))
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)

    async def _finish_playbook_bg(self, gid, effect, ekey, task, wait_id) -> None:
        try:
            exc = task.exception()
            if exc is not None:
                await self._playbook_failed(gid, effect, ekey, f"{type(exc).__name__}: {exc}")
            else:
                await self._record_playbook_result(gid, effect, ekey, task.result())
        except Exception as e:  # noqa: BLE001
            log.warning("recording background playbook result failed: %s", e)
        if wait_id is not None and self._waits is not None:
            try:
                await self._waits.resolve(wait_id, note="playbook run completed")
                if self._runtime is not None:
                    await self._runtime._wake_goal(  # noqa: SLF001 — same-package seam
                        str(gid), reason="playbook run completed"
                    )
            except Exception as e:  # noqa: BLE001
                log.warning("resolving playbook wait failed: %s", e)

    async def _playbook_failed(self, gid, effect, ekey, error: str) -> dict[str, Any]:
        async with self._sf() as s:
            self._event(
                s, gid, "effect_failed",
                {"effect_key": ekey, "playbook": effect["payload"]["playbook"],
                 "error": error},
            )
            await s.commit()
        return {"status": "failed", "error": error,
                "note": "a failed playbook run is never a confirmed step — re-plan or fix the playbook"}

    async def _record_playbook_result(self, gid, effect, ekey, raw) -> dict[str, Any]:
        """playbook_run returns a JSON string; translate its shapes into the
        honest evidence trail. A failed or approval-gated run is NEVER
        confirmed."""
        name = effect["payload"]["playbook"]
        try:
            data = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (ValueError, TypeError):
            return await self._playbook_failed(
                gid, effect, ekey, f"unparseable playbook_run result: {str(raw)[:200]}"
            )

        if data.get("error"):
            return await self._playbook_failed(gid, effect, ekey, str(data["error"]))

        if data.get("needs_approval"):
            # The playbook's own autonomy gate (manual_only / agent_must_confirm).
            async with self._sf() as s:
                self._event(
                    s, gid, "policy_block",
                    {"family": "approval", "effect_key": ekey,
                     "reason": f"playbook '{name}' requires owner approval "
                               f"(autonomy '{data.get('current_autonomy')}')",
                     "remedy": "raise its autonomy with playbook_set_autonomy "
                               "(this shows the owner an approval card), then retry",
                     "attempted": {"kind": "playbook_run", "playbook": name}},
                )
                await s.commit()
            return {
                "status": "blocked",
                "family": "approval",
                "reason": f"playbook '{name}' requires owner approval (autonomy "
                          f"'{data.get('current_autonomy')}')",
                "remedy": "raise its autonomy with playbook_set_autonomy (this "
                          "shows the owner an approval card), then retry goal_effect",
            }

        run_id = data.get("run_id")
        status = data.get("status")
        if status == "done":
            evidence = _result_evidence(data.get("step_results") or data)
            async with self._sf() as s:
                self._event(
                    s, gid, "effect_confirmed",
                    {"effect_kind": "playbook_run", "tool": "playbook_run",
                     "playbook": name, "run_id": run_id,
                     "effect_key": ekey, "target": effect.get("target"), **evidence},
                )
                await s.commit()
            return {"status": "done", "run_id": run_id,
                    "result": data.get("step_results") or {}, **evidence}

        # failed / cancelled / anything not-done
        return await self._playbook_failed(
            gid, effect, ekey,
            f"playbook run {run_id or '?'} ended with status '{status}'"
            + (" — check playbook_status for the failing step" if status == "failed" else ""),
        )
