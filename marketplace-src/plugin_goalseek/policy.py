"""The policy engine — eight predicate families, pure functions, no luna_sdk.

``evaluate(goal, effect, context)`` runs the families in a fixed order and the
first non-allow decision wins. Everything is plain dicts so the whole engine
unit-tests without a database or the Luna runtime.

Every block carries an owner-readable ``reason`` and — the self-tuning
contract — a ``remedy``: what knowledge or action would make the same attempt
pass next time. A block without a remedy is a bug.

Shapes
------
goal (dict): the ``_goal_dict`` shape from tools.py — ``stage``,
    ``autonomy_level``, ``risk_ceiling`` are what the families read.
effect (dict): ``{"kind": "tool_call", "payload": {"tool", "args"},
    "risk": "low|medium|high", "target": str|None, "writes_fact": str|None,
    "channel": str|None, "contact": str|None}``. ``risk``/``target``/… are
    declared by the caller (the agent) and checked against policy; lying about
    them is recorded in the evidence trail either way.
context (dict): ``{"now": datetime, "policies": [policy dicts],
    "facts": {key: fact dict}, "recent_events": [event dicts newest-first],
    "turn_effect_keys": set[str]}``. ``now`` is always injected — predicates
    never call ``datetime.now()`` themselves (test flakiness rule).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

FAMILIES = (
    "lifecycle",
    "permission",
    "eligibility",
    "consent",
    "timing",
    "sequencing",
    "data_authority",
    "approval",
)


@dataclass
class Decision:
    kind: Literal["allow", "block", "needs_approval"]
    family: str | None = None
    reason: str | None = None
    remedy: str | None = None
    card: dict | None = None

    @property
    def allowed(self) -> bool:
        return self.kind == "allow"


ALLOW = Decision(kind="allow")


def _params_for(policies: list[dict], family: str) -> list[dict]:
    """Enabled policy rows for one family. Goal-scoped rows come after global
    ones so goal params override on key collision when merged."""
    rows = [p for p in policies or [] if p.get("family") == family and p.get("enabled", True)]
    rows.sort(key=lambda p: 0 if p.get("goal_id") is None else 1)
    return rows


def _merged_params(policies: list[dict], family: str) -> dict:
    merged: dict = {}
    for row in _params_for(policies, family):
        merged.update(row.get("params") or {})
    return merged


# -- family 1: lifecycle / outcome -------------------------------------------


def check_lifecycle(goal: dict, effect: dict, context: dict) -> Decision:
    stage = goal.get("stage")
    if stage == "closed":
        return Decision(
            kind="block",
            family="lifecycle",
            reason=f"goal is closed ({goal.get('outcome')}) — closed goals cannot act",
            remedy="open a new goal if this outcome still matters; closed lifecycles are immutable",
        )
    if stage != "active":
        return Decision(
            kind="block",
            family="lifecycle",
            reason=f"goal stage is '{stage}' — only active goals may act",
            remedy=(
                "move the goal to 'active' first (goal_update stage='active'); "
                "proposed goals need owner ratification"
            ),
        )
    return ALLOW


# -- family 2: permission / scope --------------------------------------------


def check_permission(goal: dict, effect: dict, context: dict) -> Decision:
    params = _merged_params(context.get("policies", []), "permission")
    allowed_effects = params.get("allowed_effects")
    kind = effect.get("kind")
    if allowed_effects is not None and kind not in allowed_effects:
        return Decision(
            kind="block",
            family="permission",
            reason=f"effect kind '{kind}' is not allowed for this goal (allowed: {allowed_effects})",
            remedy="use an allowed effect kind, or ask the owner to widen this goal's allowed_effects policy",
        )
    effect_risk = effect.get("risk", "medium")
    ceiling = goal.get("risk_ceiling", "medium")
    if RISK_ORDER.get(effect_risk, 1) > RISK_ORDER.get(ceiling, 1):
        return Decision(
            kind="block",
            family="permission",
            reason=f"effect risk '{effect_risk}' exceeds this goal's risk ceiling '{ceiling}'",
            remedy=(
                "find a lower-risk way to achieve the same step, or ask the owner "
                "to raise the goal's risk_ceiling"
            ),
        )
    if kind == "playbook_run":
        allowed_playbooks = params.get("allowed_playbooks")
        pb = (effect.get("payload") or {}).get("playbook")
        if allowed_playbooks is not None and pb not in allowed_playbooks:
            return Decision(
                kind="block",
                family="permission",
                reason=f"playbook '{pb}' is not in this goal's allowed_playbooks ({allowed_playbooks})",
                remedy="run an allowed playbook, or ask the owner to add this one to allowed_playbooks",
            )
    denied_tools = params.get("denied_tools") or []
    tool = (effect.get("payload") or {}).get("tool")
    if tool and tool in denied_tools:
        return Decision(
            kind="block",
            family="permission",
            reason=f"tool '{tool}' is denied by policy for this goal",
            remedy="achieve the step with a different tool, or ask the owner to relax the denied_tools policy",
        )
    return ALLOW


# -- family 3: eligibility / precondition --------------------------------------


def check_eligibility(goal: dict, effect: dict, context: dict) -> Decision:
    params = _merged_params(context.get("policies", []), "eligibility")
    required = params.get("requires_facts") or []
    facts = context.get("facts") or {}
    missing = [k for k in required if k not in facts]
    if missing:
        return Decision(
            kind="block",
            family="eligibility",
            reason=f"required facts missing before acting: {missing}",
            remedy=(
                f"gather {missing} first (ask the owner, check the wiki/CRM, research) "
                "and store each with goal_fact_set — then retry"
            ),
        )
    return ALLOW


# -- family 4: consent / communication -----------------------------------------


def check_consent(goal: dict, effect: dict, context: dict) -> Decision:
    facts = context.get("facts") or {}
    contact = effect.get("contact")
    if contact:
        dnc_fact = facts.get("do_not_contact")
        dnc_list = _fact_value(dnc_fact) or []
        if isinstance(dnc_list, str):
            dnc_list = [dnc_list]
        if contact in dnc_list:
            return Decision(
                kind="block",
                family="consent",
                reason=f"'{contact}' is on this goal's do_not_contact list",
                remedy=(
                    "do not message this contact; pursue the goal through another "
                    "route, or ask the owner to lift the restriction"
                ),
            )
    params = _merged_params(context.get("policies", []), "consent")
    allowed_channels = params.get("allowed_channels")
    channel = effect.get("channel")
    if channel and allowed_channels is not None and channel not in allowed_channels:
        return Decision(
            kind="block",
            family="consent",
            reason=f"channel '{channel}' is not allowed for this goal (allowed: {allowed_channels})",
            remedy=f"use one of {allowed_channels}, or ask the owner to allow '{channel}'",
        )
    return ALLOW


# -- family 5: timing / pacing --------------------------------------------------


def _parse_window(spec: str) -> tuple[int, int] | None:
    """'9-17' or '09:00-17:30' -> (start_minutes, end_minutes). None = invalid."""
    try:
        start_s, end_s = str(spec).split("-", 1)

        def _mins(part: str) -> int:
            part = part.strip()
            if ":" in part:
                h, m = part.split(":", 1)
                return int(h) * 60 + int(m)
            return int(part) * 60

        return _mins(start_s), _mins(end_s)
    except (ValueError, AttributeError):
        return None


def _fact_value(fact: dict | None) -> Any:
    if fact is None:
        return None
    value = fact.get("value")
    if isinstance(value, dict) and set(value.keys()) == {"v"}:
        return value["v"]
    return value


def check_timing(goal: dict, effect: dict, context: dict) -> Decision:
    params = _merged_params(context.get("policies", []), "timing")
    facts = context.get("facts") or {}
    now: datetime = context["now"]

    # Working-hours window: the goal fact wins over the policy default.
    window_spec = _fact_value(facts.get("working_hours")) or params.get("working_hours")
    if window_spec and effect.get("contact"):
        window = _parse_window(window_spec)
        if window is not None:
            start_m, end_m = window
            now_m = now.hour * 60 + now.minute
            if not (start_m <= now_m < end_m):
                return Decision(
                    kind="block",
                    family="timing",
                    reason=(
                        f"outside the working-hours window ({window_spec}) for contact "
                        f"'{effect['contact']}' — it is now {now.strftime('%H:%M')}"
                    ),
                    remedy=(
                        "schedule this inside the window instead of sending now; if the "
                        "window is wrong, update the goal fact 'working_hours'"
                    ),
                )

    # Quiet hours (phase 05 owner setting, injected as a timing param): the
    # INVERSE of working hours — outreach must NOT happen inside the window.
    # A window like "22-8" wraps midnight.
    quiet_spec = params.get("quiet_hours")
    if quiet_spec and effect.get("contact"):
        window = _parse_window(quiet_spec)
        if window is not None:
            start_m, end_m = window
            now_m = now.hour * 60 + now.minute
            inside = (start_m <= now_m < end_m) if start_m <= end_m \
                else (now_m >= start_m or now_m < end_m)
            if inside:
                return Decision(
                    kind="block",
                    family="timing",
                    reason=(
                        f"inside the owner's quiet hours ({quiet_spec}) for contact "
                        f"'{effect['contact']}' — it is now {now.strftime('%H:%M')}"
                    ),
                    remedy=(
                        "wait until quiet hours end (schedule it), or ask the owner "
                        "to change the quiet_hours setting"
                    ),
                )

    # Cooldown between same-kind effects.
    cooldown_min = params.get("cooldown_minutes")
    if cooldown_min:
        last = _last_effect_at(context.get("recent_events") or [], effect.get("kind"))
        if last is not None and now - last < timedelta(minutes=float(cooldown_min)):
            wait = int((timedelta(minutes=float(cooldown_min)) - (now - last)).total_seconds() // 60) + 1
            return Decision(
                kind="block",
                family="timing",
                reason=(
                    f"cooldown: a '{effect.get('kind')}' effect ran "
                    f"{int((now - last).total_seconds() // 60)} min ago "
                    f"(policy: {cooldown_min} min between attempts)"
                ),
                remedy=f"wait ~{wait} more minutes, or do non-effect work (research, planning) meanwhile",
            )

    # Per-window cap.
    cap = params.get("window_cap")
    window_hours = params.get("window_hours", 24)
    if cap:
        cutoff = now - timedelta(hours=float(window_hours))
        count = _count_effects_since(context.get("recent_events") or [], cutoff)
        if count >= int(cap):
            return Decision(
                kind="block",
                family="timing",
                reason=f"effect cap reached: {count}/{cap} effects in the last {window_hours}h",
                remedy="pause acting until the window rolls over; use the time to verify results so far",
            )

    # Duplicate effect within one turn.
    key = effect_key(effect)
    if key in (context.get("turn_effect_keys") or set()):
        return Decision(
            kind="block",
            family="timing",
            reason="duplicate effect: the identical call already ran this turn",
            remedy="do not repeat the call — read its recorded result from the event trail instead",
        )
    return ALLOW


def effect_key(effect: dict) -> str:
    import hashlib
    import json

    raw = json.dumps(
        {"kind": effect.get("kind"), "payload": effect.get("payload")},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _last_effect_at(recent_events: list[dict], kind: str | None) -> datetime | None:
    for e in recent_events:
        if e.get("kind") == "effect_confirmed" and (
            kind is None or (e.get("payload") or {}).get("effect_kind") == kind
        ):
            at = e.get("at")
            if isinstance(at, datetime):
                return at
            if isinstance(at, str):
                try:
                    return datetime.fromisoformat(at)
                except ValueError:
                    return None
    return None


def _count_effects_since(recent_events: list[dict], cutoff: datetime) -> int:
    n = 0
    for e in recent_events:
        if e.get("kind") not in ("effect_confirmed", "effect_attempted"):
            continue
        at = e.get("at")
        if isinstance(at, str):
            try:
                at = datetime.fromisoformat(at)
            except ValueError:
                continue
        if isinstance(at, datetime) and at >= cutoff and e.get("kind") == "effect_confirmed":
            n += 1
    return n


# -- family 6: sequencing / completion ------------------------------------------


def check_sequencing(goal: dict, effect: dict, context: dict) -> Decision:
    params = _merged_params(context.get("policies", []), "sequencing")
    if params.get("verify_before_write") and effect.get("is_write"):
        target = effect.get("target")
        events = context.get("recent_events") or []
        verified = any(
            e.get("kind") in ("effect_confirmed", "note", "fact_set")
            and (e.get("payload") or {}).get("target") == target
            and (e.get("payload") or {}).get("verify") is True
            for e in events
        )
        if not verified:
            return Decision(
                kind="block",
                family="sequencing",
                reason=f"verify-before-write: no recorded verification of target '{target}' precedes this write",
                remedy=(
                    "read/verify the target first and record it (goal_effect with a read, "
                    "or a note with verify=true payload), then retry the write"
                ),
            )
    return ALLOW


# -- family 7: data-authority ----------------------------------------------------


def check_data_authority(goal: dict, effect: dict, context: dict) -> Decision:
    writes_fact = effect.get("writes_fact")
    if writes_fact:
        fact = (context.get("facts") or {}).get(writes_fact)
        if fact is not None and fact.get("authority") in ("human", "system"):
            return Decision(
                kind="block",
                family="data_authority",
                reason=(
                    f"fact '{writes_fact}' has {fact.get('authority')} authority — "
                    "the agent may not overwrite it"
                ),
                remedy=(
                    "record your proposed value as a goal note and ask the owner to "
                    "update the fact; do not overwrite it"
                ),
            )
    return ALLOW


# -- family 8: approval / autonomy -----------------------------------------------


def check_approval(goal: dict, effect: dict, context: dict) -> Decision:
    level = int(goal.get("autonomy_level", 3))
    if level == 1:
        return Decision(
            kind="block",
            family="approval",
            reason="autonomy level 1 (observe & advise) — this goal may not take effects",
            remedy=(
                "report your recommendation to the owner instead; they can raise the "
                "goal's autonomy level if they want you acting"
            ),
        )
    if level == 2:
        return Decision(
            kind="needs_approval",
            family="approval",
            reason="autonomy level 2 (act with approval) — every consequential effect needs an owner card",
            card={
                "intent": effect.get("intent") or "goal effect",
                "effect": {"kind": effect.get("kind"), "payload": effect.get("payload")},
            },
        )
    return ALLOW


_CHECKS = (
    check_lifecycle,
    check_permission,
    check_eligibility,
    check_consent,
    check_timing,
    check_sequencing,
    check_data_authority,
    check_approval,
)


def evaluate(goal: dict, effect: dict, context: dict) -> Decision:
    """Run all families in order; first non-allow wins."""
    for check in _CHECKS:
        decision = check(goal, effect, context)
        if decision.kind != "allow":
            return decision
    return ALLOW
