"""The per-turn prompt block: keeps chat-Luna aware of goals it is pursuing.

Bottom-line first, one line per goal, capped — zero prompt tax when idle.
Pure formatting; the plugin's ``prompt_sections()`` feeds it store data.
"""

from __future__ import annotations

from typing import Any

MAX_GOALS_SHOWN = 5


def _goal_line(g: dict[str, Any]) -> str:
    bits = [f"- [{g['stage']}] {g['statement']}"]
    bits.append(f" — done means: {g['definition_of_done']}")
    if g.get("deadline"):
        bits.append(f" Deadline {g['deadline'][:10]}.")
    return "".join(bits)


def goals_fragment(
    goals: list[dict[str, Any]],
    reflections: dict[str, str] | None = None,
) -> str | None:
    """Render the prompt block, or None when there is nothing to say.

    ``reflections`` (phase 02): goal_id -> tuning reflection text for goals
    that keep hitting policy gates — surfaced right under the goal line so the
    agent closes the knowledge gap instead of retrying into the wall.
    """
    live = [g for g in goals if g["stage"] != "closed"]
    if not live:
        return None
    lines = ["## Active goals (goal-seek)"]
    proposed = [g for g in live if g["stage"] == "proposed"]
    shown = live[:MAX_GOALS_SHOWN]
    for g in shown:
        lines.append(_goal_line(g))
        reflection = (reflections or {}).get(g["id"])
        if reflection:
            first = reflection.splitlines()[0]
            lines.append(f"  ⚠ {first}")
    if len(live) > MAX_GOALS_SHOWN:
        lines.append(f"…and {len(live) - MAX_GOALS_SHOWN} more (goal_list).")
    if proposed:
        lines.append(
            f"{len(proposed)} proposed goal(s) await owner ratification "
            "(goal_update stage='active')."
        )
    lines.append(
        "Work goals through their tools: goal_get before acting, goal_effect "
        "for consequential actions (it enforces this goal's policies and "
        "returns a remedy when blocked — follow it), goal_update after "
        "progress, goal_close (with outcome + reason) when done."
    )
    return "\n".join(lines)
