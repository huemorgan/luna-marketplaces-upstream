"""Agent-facing interview tools. Thin handlers: persistence via InterviewStore,
math via service, methodology via prompts. Writes touch only plugin tables, so
all tools use the default auto_approve policy (no approval prompts on the loop)."""

from __future__ import annotations

from typing import Any

from luna_sdk import PluginContext, ToolDef

from . import service
from .prompts import METHODOLOGY
from .store import InterviewNotFound, InterviewStore


def register_tools(ctx: PluginContext, store: InterviewStore) -> None:
    events = ctx.events

    async def _start(
        goal: str, title: str | None = None, target_min: int | None = None,
        target_pct: int | None = None,
    ) -> dict[str, Any]:
        sess = await store.create(
            goal=goal,
            title=title,
            target_min=target_min or service.DEFAULT_TARGET_MIN,
            target_pct=target_pct or service.DEFAULT_TARGET_PCT,
        )
        await events.emit(
            "interview.started",
            {"interview_id": str(sess.id), "goal": goal},
        )
        return {
            "interview_id": str(sess.id),
            "status": sess.status,
            "methodology": METHODOLOGY,
            "next_step": (
                "Research the domain, then call interview_set_topics to seed the "
                "coverage map. Then ask ONE question at a time."
            ),
        }

    async def _set_topics(
        interview_id: str,
        topics: list[dict[str, Any]],
        domain: str | None = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        try:
            return await store.set_topics(
                interview_id, topics, domain=domain, replace=replace
            )
        except InterviewNotFound:
            return {"error": f"no interview {interview_id}"}

    async def _record_answer(
        interview_id: str,
        question: str,
        answer: str,
        coverage: list[dict[str, Any]],
        add_topics: list[dict[str, Any]] | None = None,
        drop_topics: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        if not coverage:
            return {
                "error": (
                    "coverage is required — score every topic this answer touched "
                    "(0–10 + notes) so the interview stays adaptive."
                )
            }
        try:
            result = await store.record_answer(
                interview_id,
                question=question,
                answer=answer,
                coverage=coverage,
                add_topics=add_topics,
                drop_topics=drop_topics,
                constraints=constraints,
            )
        except InterviewNotFound:
            return {"error": f"no interview {interview_id}"}
        await events.emit(
            "interview.answer_recorded",
            {
                "interview_id": interview_id,
                "seq": result["seq"],
                "coverage_pct": result["coverage_pct"],
                "ready": result["ready"],
            },
        )
        return result

    async def _revise_topics(
        interview_id: str, updates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        try:
            return await store.revise_topics(interview_id, updates)
        except InterviewNotFound:
            return {"error": f"no interview {interview_id}"}

    async def _next(interview_id: str) -> dict[str, Any]:
        try:
            state = await store.state(interview_id)
        except InterviewNotFound:
            return {"error": f"no interview {interview_id}"}
        views = [
            service.TopicView(
                key=t["key"], title=t["title"], why=t["why"],
                priority=t["priority"], status=t["status"], coverage=t["coverage"],
                sort=t["sort"],
            )
            for t in state["topics"]
        ]
        summary = service.summarize(
            views, target_min=state["target_min"], target_pct=state["target_pct"]
        )
        return {
            "coverage_pct": summary.coverage_pct,
            "ready": summary.ready,
            "next_focus": summary.next_focus,
            "suggestion": summary.suggestion,
        }

    async def _get(interview_id: str) -> dict[str, Any]:
        try:
            return await store.state(interview_id)
        except InterviewNotFound:
            return {"error": f"no interview {interview_id}"}

    async def _brief(interview_id: str) -> dict[str, Any]:
        try:
            return {"brief": await store.brief(interview_id)}
        except InterviewNotFound:
            return {"error": f"no interview {interview_id}"}

    async def _list() -> dict[str, Any]:
        return {"interviews": await store.list()}

    async def _complete(interview_id: str) -> dict[str, Any]:
        try:
            state = await store.complete(interview_id)
        except InterviewNotFound:
            return {"error": f"no interview {interview_id}"}
        await events.emit(
            "interview.completed",
            {"interview_id": interview_id, "coverage_pct": state["coverage_pct"]},
        )
        brief = await store.brief(interview_id)
        return {"status": state["status"], "coverage_pct": state["coverage_pct"], "brief": brief}

    _topic_item = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Slug, unique within the interview."},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "why": {"type": "string", "description": "Why this topic matters to the goal."},
            "priority": {
                "type": "string",
                "enum": list(service.VALID_PRIORITIES),
            },
        },
        "required": ["key"],
    }

    defs: list[tuple[ToolDef, Any]] = [
        (
            ToolDef(
                name="interview_start",
                description=(
                    "Begin an adaptive knowledge-elicitation interview for a goal "
                    "(e.g. 'create a website'). Returns an interview_id and the full "
                    "methodology to follow. Call this when the user wants help turning "
                    "a vague idea into a structured brief."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "What the user wants to create."},
                        "title": {"type": "string"},
                        "target_min": {"type": "integer", "description": "Per-topic min score for 'covered' (default 7)."},
                        "target_pct": {"type": "integer", "description": "Weighted coverage %% for 'ready' (default 80)."},
                    },
                    "required": ["goal"],
                },
            ),
            _start,
        ),
        (
            ToolDef(
                name="interview_set_topics",
                description=(
                    "Seed or extend the coverage map after researching the domain. "
                    "Optionally store your researched domain understanding via `domain`. "
                    "Set replace=true to overwrite the whole map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "interview_id": {"type": "string"},
                        "topics": {"type": "array", "items": _topic_item},
                        "domain": {"type": "string", "description": "Short researched brief of the domain."},
                        "replace": {"type": "boolean", "default": False},
                    },
                    "required": ["interview_id", "topics"],
                },
            ),
            _set_topics,
        ),
        (
            ToolDef(
                name="interview_record_answer",
                description=(
                    "Record a Q&A turn. REQUIRED each turn: `coverage` — for every "
                    "topic the answer touched, a 0–10 score + short notes. Adapt the "
                    "map with add_topics/drop_topics and capture hard `constraints`. "
                    "Returns updated coverage and the next focus."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "interview_id": {"type": "string"},
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                        "coverage": {
                            "type": "array",
                            "description": "Per-topic coverage updates from this answer.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "topic": {"type": "string", "description": "Topic key."},
                                    "score": {"type": "integer", "description": "0–10 coverage."},
                                    "notes": {"type": "string"},
                                },
                                "required": ["topic", "score"],
                            },
                        },
                        "add_topics": {"type": "array", "items": _topic_item},
                        "drop_topics": {"type": "array", "items": {"type": "string"}},
                        "constraints": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["interview_id", "question", "answer", "coverage"],
                },
            ),
            _record_answer,
        ),
        (
            ToolDef(
                name="interview_revise_topics",
                description="Edit topics (rename / re-prioritize / change why) without recording an answer.",
                parameters={
                    "type": "object",
                    "properties": {
                        "interview_id": {"type": "string"},
                        "updates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "title": {"type": "string"},
                                    "why": {"type": "string"},
                                    "priority": {"type": "string", "enum": list(service.VALID_PRIORITIES)},
                                    "status": {"type": "string", "enum": ["pending", "active", "covered", "dropped"]},
                                },
                                "required": ["key"],
                            },
                        },
                    },
                    "required": ["interview_id", "updates"],
                },
            ),
            _revise_topics,
        ),
        (
            ToolDef(
                name="interview_next",
                description="Get focus guidance: least-covered, highest-priority topics + a suggested angle. You write the actual question.",
                parameters={
                    "type": "object",
                    "properties": {"interview_id": {"type": "string"}},
                    "required": ["interview_id"],
                },
            ),
            _next,
        ),
        (
            ToolDef(
                name="interview_get",
                description="Full compact interview state: session + topics (coverage/status/notes) + recent turns.",
                parameters={
                    "type": "object",
                    "properties": {"interview_id": {"type": "string"}},
                    "required": ["interview_id"],
                },
            ),
            _get,
        ),
        (
            ToolDef(
                name="interview_brief",
                description="Render the markdown Q&A / brief from the interview state.",
                parameters={
                    "type": "object",
                    "properties": {"interview_id": {"type": "string"}},
                    "required": ["interview_id"],
                },
            ),
            _brief,
        ),
        (
            ToolDef(
                name="interview_list",
                description="List the user's interviews with status + coverage.",
                parameters={"type": "object", "properties": {}},
            ),
            _list,
        ),
        (
            ToolDef(
                name="interview_complete",
                description="Mark the interview complete and return the final brief.",
                parameters={
                    "type": "object",
                    "properties": {"interview_id": {"type": "string"}},
                    "required": ["interview_id"],
                },
            ),
            _complete,
        ),
    ]

    for tool_def, handler in defs:
        ctx.tool_registry.register("plugin-interview", tool_def, handler)
