"""Pure lifecycle rules — no ``luna_sdk`` import, fully unit-testable.

Stages, the transition whitelist, and close validation (base outcomes +
per-goal business labels + structured reasons). The "closed goal cannot act"
invariant starts here: :func:`is_terminal` guards every mutation in tools.py.
"""

from __future__ import annotations

from typing import Any

STAGES = ("proposed", "active", "parked", "waiting", "closing", "closed")

BASE_OUTCOMES = ("achieved", "failed", "abandoned", "escalated", "expired")

AUTONOMY_LEVELS = (1, 2, 3)  # observe & advise | act with approval | act freely

RISK_LEVELS = ("low", "medium", "high")

# stage -> stages reachable from it
_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "proposed": ("active", "closed"),  # approve / reject
    "active": ("parked", "waiting", "closing", "closed"),
    "parked": ("active", "closed"),
    "waiting": ("active", "closing", "closed"),
    "closing": ("active", "closed"),  # closing review may bounce back
    "closed": (),
}


def can_transition(stage_from: str, stage_to: str) -> bool:
    return stage_to in _TRANSITIONS.get(stage_from, ())


def is_terminal(stage: str) -> bool:
    return stage == "closed"


def validate_outcome_labels(labels: Any) -> str | None:
    """Validate a goal_open ``outcome_labels`` map. Returns an error string
    or None. Empty map is fine — the five base outcomes always work."""
    if labels is None:
        return None
    if not isinstance(labels, dict):
        return "outcome_labels must be a map of {business label: base outcome}"
    for label, base in labels.items():
        if not isinstance(label, str) or not label.strip():
            return "outcome_labels keys must be non-empty strings"
        if base not in BASE_OUTCOMES:
            return (
                f"outcome_labels[{label!r}] maps to {base!r} — "
                f"must be one of {BASE_OUTCOMES}"
            )
    return None


def validate_close(
    *,
    stage: str,
    outcome: str,
    outcome_label: str | None,
    outcome_labels: dict[str, str],
    reason: Any,
) -> str | None:
    """Validate a goal_close call. Returns an error string or None (valid).

    Rules:
    - goal must not already be terminal;
    - ``outcome`` must be one of the five base outcomes (hard enum);
    - a business ``outcome_label`` must exist in the goal's map and map to
      the passed base outcome;
    - ``reason`` must be a dict with a non-empty ``summary``; a ``failed``
      close additionally requires a non-empty ``cause``.
    """
    if is_terminal(stage):
        return "goal is already closed"
    if outcome not in BASE_OUTCOMES:
        return f"outcome must be one of {BASE_OUTCOMES}, got {outcome!r}"
    if outcome_label is not None:
        mapped = (outcome_labels or {}).get(outcome_label)
        if mapped is None:
            known = sorted((outcome_labels or {}).keys())
            return (
                f"unknown business label {outcome_label!r} — this goal defines {known}"
            )
        if mapped != outcome:
            return (
                f"label {outcome_label!r} maps to base outcome {mapped!r}, "
                f"not {outcome!r}"
            )
    if not isinstance(reason, dict) or not str(reason.get("summary", "")).strip():
        return "reason must be a dict with a non-empty 'summary'"
    if outcome == "failed" and not str(reason.get("cause", "")).strip():
        return "a 'failed' close requires reason.cause — what caused the failure"
    return None


def validate_open(
    *,
    statement: str,
    definition_of_done: str,
    autonomy_level: int,
    risk_ceiling: str,
    outcome_labels: Any,
) -> str | None:
    """Validate goal_open arguments. Returns an error string or None."""
    if not (statement or "").strip():
        return "statement must be non-empty"
    if not (definition_of_done or "").strip():
        return "definition_of_done must be non-empty — a goal without a done test is a topic"
    if autonomy_level not in AUTONOMY_LEVELS:
        return f"autonomy_level must be one of {AUTONOMY_LEVELS} (1=observe & advise, 2=act with approval, 3=act freely)"
    if risk_ceiling not in RISK_LEVELS:
        return f"risk_ceiling must be one of {RISK_LEVELS}"
    return validate_outcome_labels(outcome_labels)
