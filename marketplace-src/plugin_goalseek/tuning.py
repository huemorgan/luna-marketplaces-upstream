"""Self-tuning: policy hits are a training signal, not just enforcement.

Pure functions over event dicts. A goal that keeps hitting the same gate is a
goal whose knowledge or plan is mistuned — the reflection text tells the agent
to close the gap (using the remedies already recorded in the block events)
instead of retrying into the wall.

Thresholds are constants for now; phase 05 moves them into the settings UI.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# Warn when one family blocked this goal >= N times.
FAMILY_HIT_THRESHOLD = 3
# Warn when blocks / attempts over the recent window exceeds this.
RATE_THRESHOLD = 0.25
RATE_WINDOW = 20  # most recent attempts considered


def gate_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute block counts per family + the recent hit rate.

    ``events`` newest-first (the goal_get shape). Attempts are
    ``effect_requested`` events; hits are ``policy_block``.
    """
    family_hits: Counter[str] = Counter()
    recent_attempts = 0
    recent_blocks = 0
    for e in events:
        kind = e.get("kind")
        if kind == "policy_block":
            fam = (e.get("payload") or {}).get("family") or "unknown"
            family_hits[fam] += 1
        if kind in ("effect_requested",) and recent_attempts < RATE_WINDOW:
            recent_attempts += 1
        if kind == "policy_block" and recent_attempts < RATE_WINDOW:
            recent_blocks += 1
    rate = (recent_blocks / recent_attempts) if recent_attempts else 0.0
    return {
        "family_hits": dict(family_hits),
        "attempts": recent_attempts,
        "blocks": recent_blocks,
        "rate": round(rate, 3),
    }


def _worst_family(stats: dict[str, Any]) -> tuple[str, int] | None:
    hits = stats.get("family_hits") or {}
    if not hits:
        return None
    fam, n = max(hits.items(), key=lambda kv: kv[1])
    return fam, n


def needs_reflection(stats: dict[str, Any], *, warn_hits: int | None = None,
                     warn_rate: float | None = None) -> bool:
    # Phase 05: thresholds are owner settings (tuning_warn_hits/_rate);
    # the module constants stay as the defaults.
    hits_t = warn_hits if warn_hits is not None else FAMILY_HIT_THRESHOLD
    rate_t = warn_rate if warn_rate is not None else RATE_THRESHOLD
    worst = _worst_family(stats)
    if worst and worst[1] >= hits_t:
        return True
    return stats.get("attempts", 0) >= 4 and stats.get("rate", 0.0) > rate_t


def reflection_text(stats: dict[str, Any], remedies: list[str] | None = None) -> str | None:
    """The tuning reflection injected into the goal's prompt block and
    returned alongside the next block decision. None when tuning is fine."""
    if not needs_reflection(stats):
        return None
    worst = _worst_family(stats)
    lines: list[str] = []
    if worst and worst[1] >= FAMILY_HIT_THRESHOLD:
        fam, n = worst
        lines.append(
            f"Tuning: you hit the {fam} gate {n}x on this goal. Repeated blocks "
            "mean a knowledge or planning gap — close it before acting again."
        )
    else:
        lines.append(
            f"Tuning: {stats['blocks']} of your last {stats['attempts']} effect "
            "attempts were blocked. Slow down and fix the underlying gap."
        )
    seen: set[str] = set()
    for r in remedies or []:
        if r and r not in seen:
            seen.add(r)
            lines.append(f"- open remedy: {r}")
        if len(seen) >= 3:
            break
    return "\n".join(lines)


def recent_remedies(events: list[dict[str, Any]], limit: int = 5) -> list[str]:
    out: list[str] = []
    for e in events:
        if e.get("kind") == "policy_block":
            remedy = (e.get("payload") or {}).get("remedy")
            if remedy:
                out.append(remedy)
        if len(out) >= limit:
            break
    return out
