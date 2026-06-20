"""Pure interview logic — coverage math, topic adaptation, readiness, brief.

No DB, no LLM, no I/O. Everything here is hand-testable with plain dataclasses
so `tests/008.001-interview-plugin/` can assert exact numbers. The plugin's
tools/store convert ORM rows into these views, call these functions, and persist
the results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRIORITY_WEIGHT: dict[str, int] = {"low": 1, "normal": 2, "high": 3, "critical": 5}

VALID_PRIORITIES = tuple(PRIORITY_WEIGHT.keys())
HIGH_PRIORITIES = ("high", "critical")

DEFAULT_TARGET_MIN = 7
DEFAULT_TARGET_PCT = 80


@dataclass
class TopicView:
    """A coverage-map topic, decoupled from the ORM for pure-logic testing."""

    key: str
    title: str = ""
    description: str = ""
    why: str = ""
    priority: str = "normal"
    status: str = "pending"  # pending | active | covered | dropped
    coverage: int = 0  # 0..10
    notes: str = ""
    origin: str = "agent"  # researched | user | agent
    sort: int = 0


def weight(priority: str) -> int:
    return PRIORITY_WEIGHT.get((priority or "normal").lower(), 2)


def clamp_coverage(value: int | float | None) -> int:
    try:
        v = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(10, v))


def normalize_priority(priority: str | None) -> str:
    p = (priority or "normal").lower()
    return p if p in PRIORITY_WEIGHT else "normal"


def active_topics(topics: list[TopicView]) -> list[TopicView]:
    return [t for t in topics if t.status != "dropped"]


def coverage_pct(topics: list[TopicView]) -> float:
    """Priority-weighted coverage percentage over non-dropped topics."""
    active = active_topics(topics)
    if not active:
        return 0.0
    numerator = sum(clamp_coverage(t.coverage) * weight(t.priority) for t in active)
    denominator = sum(10 * weight(t.priority) for t in active)
    if denominator <= 0:
        return 0.0
    return round(100.0 * numerator / denominator, 1)


def status_for(coverage: int, target_min: int, current: str = "pending") -> str:
    """Derive a topic's lifecycle status from its coverage score."""
    if current == "dropped":
        return "dropped"
    cov = clamp_coverage(coverage)
    if cov >= target_min:
        return "covered"
    if cov > 0:
        return "active"
    return "pending"


def is_ready(
    topics: list[TopicView],
    *,
    target_min: int = DEFAULT_TARGET_MIN,
    target_pct: int = DEFAULT_TARGET_PCT,
) -> bool:
    """Ready = every high/critical topic meets the min AND weighted % >= target."""
    active = active_topics(topics)
    if not active:
        return False
    must_cover = [t for t in active if normalize_priority(t.priority) in HIGH_PRIORITIES]
    if any(clamp_coverage(t.coverage) < target_min for t in must_cover):
        return False
    return coverage_pct(topics) >= target_pct


def next_focus(
    topics: list[TopicView],
    *,
    target_min: int = DEFAULT_TARGET_MIN,
    limit: int = 3,
) -> list[TopicView]:
    """Least-covered, highest-priority topics still needing work.

    Sort: not-yet-covered first, then by priority weight (desc), then by
    coverage (asc), then by sort order.
    """
    candidates = [
        t
        for t in active_topics(topics)
        if clamp_coverage(t.coverage) < target_min
    ]
    candidates.sort(
        key=lambda t: (-weight(t.priority), clamp_coverage(t.coverage), t.sort)
    )
    return candidates[:limit]


@dataclass
class CoverageSummary:
    coverage_pct: float
    ready: bool
    covered: list[str] = field(default_factory=list)
    in_progress: list[dict] = field(default_factory=list)
    next_focus: list[dict] = field(default_factory=list)
    suggestion: str = ""


def summarize(
    topics: list[TopicView],
    *,
    target_min: int = DEFAULT_TARGET_MIN,
    target_pct: int = DEFAULT_TARGET_PCT,
) -> CoverageSummary:
    """Compact state for the `record_answer`/`next` tool returns."""
    active = active_topics(topics)
    covered = [t.key for t in active if clamp_coverage(t.coverage) >= target_min]
    in_progress = [
        {"topic": t.key, "coverage": clamp_coverage(t.coverage)}
        for t in active
        if 0 < clamp_coverage(t.coverage) < target_min
    ]
    focus = next_focus(topics, target_min=target_min, limit=3)
    focus_payload = [
        {
            "topic": t.key,
            "priority": normalize_priority(t.priority),
            "coverage": clamp_coverage(t.coverage),
            "why": t.why,
        }
        for t in focus
    ]
    suggestion = ""
    if focus:
        top = focus[0]
        suggestion = (
            f"{top.title or top.key} is {normalize_priority(top.priority)} priority and "
            f"only at {clamp_coverage(top.coverage)}/10"
            + (f" — {top.why}" if top.why else "")
            + ". Ask about it next."
        )
    elif active:
        suggestion = "Coverage looks strong — consider wrapping up the interview."
    return CoverageSummary(
        coverage_pct=coverage_pct(topics),
        ready=is_ready(topics, target_min=target_min, target_pct=target_pct),
        covered=covered,
        in_progress=in_progress,
        next_focus=focus_payload,
        suggestion=suggestion,
    )


def render_brief(
    *,
    title: str,
    goal: str,
    domain_brief: str,
    topics: list[TopicView],
    turns: list[dict],
    coverage: float,
    ready: bool,
) -> str:
    """Deterministic markdown brief built from interview state."""
    lines: list[str] = []
    lines.append(f"# {title or 'Interview'}")
    lines.append("")
    lines.append(f"**Goal:** {goal or '(not set)'}")
    lines.append(
        f"**Coverage:** {coverage:.0f}%  ·  **Status:** "
        + ("ready" if ready else "in progress")
    )
    lines.append("")
    if domain_brief:
        lines.append("## Domain understanding")
        lines.append("")
        lines.append(domain_brief.strip())
        lines.append("")

    lines.append("## Coverage map")
    lines.append("")
    ordered = sorted(active_topics(topics), key=lambda t: (t.sort, t.key))
    if not ordered:
        lines.append("_No topics yet._")
    for t in ordered:
        bar = _coverage_bar(clamp_coverage(t.coverage))
        lines.append(
            f"- **{t.title or t.key}** "
            f"`{bar} {clamp_coverage(t.coverage)}/10` "
            f"· {normalize_priority(t.priority)}"
        )
        if t.why:
            lines.append(f"  - _why:_ {t.why}")
        if t.notes:
            lines.append(f"  - {t.notes.strip()}")
    lines.append("")

    lines.append("## Q&A")
    lines.append("")
    if not turns:
        lines.append("_No questions answered yet._")
    for i, turn in enumerate(turns, 1):
        q = (turn.get("question") or "").strip()
        a = (turn.get("answer") or "").strip()
        lines.append(f"**Q{i}. {q}**")
        lines.append("")
        lines.append(a or "_(no answer)_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _coverage_bar(coverage: int, width: int = 10) -> str:
    filled = max(0, min(width, coverage))
    return "█" * filled + "░" * (width - filled)
