"""DB access for plugin-interview, shared by tools and routes.

Pure persistence + delegation to `service` for all math. No LLM, no agent
coupling. Decoupled: imports only SQLAlchemy + this plugin's own modules.
"""

from __future__ import annotations

import re
import uuid as _uuid
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import service
from .models import (
    InterviewSession,
    InterviewTopic,
    InterviewTurn,
)
from .service import TopicView


class InterviewNotFound(Exception):
    pass


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s or "topic"


def _to_view(t: InterviewTopic) -> TopicView:
    return TopicView(
        key=t.key,
        title=t.title,
        description=t.description,
        why=t.why,
        priority=t.priority,
        status=t.status,
        coverage=t.coverage,
        notes=t.notes,
        origin=t.origin,
        sort=t.sort,
    )


class InterviewStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        goal: str,
        title: str | None = None,
        target_min: int = service.DEFAULT_TARGET_MIN,
        target_pct: int = service.DEFAULT_TARGET_PCT,
        user_id: str | None = None,
    ) -> InterviewSession:
        async with self._sf() as s:
            row = InterviewSession(
                goal=goal or "",
                title=(title or (goal or "Interview"))[:256],
                target_min=target_min,
                target_pct=target_pct,
                status="draft",
                user_id=user_id,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return row

    async def _load(self, s: AsyncSession, interview_id: str) -> InterviewSession:
        try:
            iid = _uuid.UUID(str(interview_id))
        except (ValueError, TypeError) as e:
            raise InterviewNotFound(str(interview_id)) from e
        row = await s.get(InterviewSession, iid)
        if row is None:
            raise InterviewNotFound(str(interview_id))
        return row

    async def _topics(self, s: AsyncSession, interview_id: Any) -> list[InterviewTopic]:
        rows = (
            await s.execute(
                select(InterviewTopic)
                .where(InterviewTopic.interview_id == interview_id)
                .order_by(InterviewTopic.sort, InterviewTopic.key)
            )
        ).scalars().all()
        return list(rows)

    async def _turns(self, s: AsyncSession, interview_id: Any) -> list[InterviewTurn]:
        rows = (
            await s.execute(
                select(InterviewTurn)
                .where(InterviewTurn.interview_id == interview_id)
                .order_by(InterviewTurn.seq)
            )
        ).scalars().all()
        return list(rows)

    def _recompute(self, sess: InterviewSession, topics: list[InterviewTopic]) -> None:
        views = [_to_view(t) for t in topics]
        sess.coverage_pct = service.coverage_pct(views)
        for t in topics:
            t.status = service.status_for(t.coverage, sess.target_min, t.status)

    async def set_topics(
        self,
        interview_id: str,
        topics: list[dict[str, Any]],
        *,
        domain: str | None = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        async with self._sf() as s:
            sess = await self._load(s, interview_id)
            if domain is not None:
                sess.domain_brief = domain
            if sess.status == "draft":
                sess.status = "active"
            if replace:
                await s.execute(
                    sa_delete(InterviewTopic).where(
                        InterviewTopic.interview_id == sess.id
                    )
                )
                await s.flush()
            existing = {t.key: t for t in await self._topics(s, sess.id)}
            next_sort = (max((t.sort for t in existing.values()), default=-1)) + 1
            for spec in topics or []:
                key = _slug(spec.get("key") or spec.get("title") or "")
                row = existing.get(key)
                if row is None:
                    row = InterviewTopic(
                        interview_id=sess.id,
                        key=key,
                        sort=next_sort,
                        origin=spec.get("origin") or "researched",
                    )
                    next_sort += 1
                    s.add(row)
                    existing[key] = row
                row.title = spec.get("title") or row.title or key
                row.description = spec.get("description") or row.description or ""
                row.why = spec.get("why") or row.why or ""
                row.priority = service.normalize_priority(spec.get("priority"))
            await s.flush()
            topics_rows = await self._topics(s, sess.id)
            self._recompute(sess, topics_rows)
            await s.commit()
            return await self._state(s, sess.id)

    async def record_answer(
        self,
        interview_id: str,
        *,
        question: str,
        answer: str,
        coverage: list[dict[str, Any]],
        add_topics: list[dict[str, Any]] | None = None,
        drop_topics: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        async with self._sf() as s:
            sess = await self._load(s, interview_id)
            if sess.status in ("draft",):
                sess.status = "active"
            topics = {t.key: t for t in await self._topics(s, sess.id)}
            next_sort = (max((t.sort for t in topics.values()), default=-1)) + 1

            for spec in add_topics or []:
                key = _slug(spec.get("key") or spec.get("title") or "")
                if key in topics:
                    continue
                row = InterviewTopic(
                    interview_id=sess.id,
                    key=key,
                    title=spec.get("title") or key,
                    why=spec.get("why") or "",
                    description=spec.get("description") or "",
                    priority=service.normalize_priority(spec.get("priority")),
                    origin=spec.get("origin") or "agent",
                    sort=next_sort,
                )
                next_sort += 1
                s.add(row)
                topics[key] = row

            for key in drop_topics or []:
                row = topics.get(_slug(key))
                if row is not None:
                    row.status = "dropped"

            for item in coverage or []:
                key = _slug(item.get("topic") or item.get("key") or "")
                row = topics.get(key)
                if row is None:
                    row = InterviewTopic(
                        interview_id=sess.id,
                        key=key,
                        title=item.get("topic") or key,
                        origin="agent",
                        sort=next_sort,
                    )
                    next_sort += 1
                    s.add(row)
                    topics[key] = row
                row.coverage = service.clamp_coverage(item.get("score"))
                notes = (item.get("notes") or "").strip()
                if notes:
                    row.notes = notes

            seq_rows = await self._turns(s, sess.id)
            seq = (max((t.seq for t in seq_rows), default=0)) + 1
            s.add(
                InterviewTurn(
                    interview_id=sess.id,
                    seq=seq,
                    question=question or "",
                    answer=answer or "",
                    touched=coverage or [],
                    constraints=constraints or [],
                )
            )
            await s.flush()
            topic_rows = await self._topics(s, sess.id)
            self._recompute(sess, topic_rows)
            await s.commit()

            views = [_to_view(t) for t in topic_rows]
            summary = service.summarize(
                views, target_min=sess.target_min, target_pct=sess.target_pct
            )
            return {
                "interview_id": str(sess.id),
                "seq": seq,
                "coverage_pct": summary.coverage_pct,
                "ready": summary.ready,
                "covered": summary.covered,
                "in_progress": summary.in_progress,
                "next_focus": summary.next_focus,
                "suggestion": summary.suggestion,
            }

    async def revise_topics(
        self, interview_id: str, updates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        async with self._sf() as s:
            sess = await self._load(s, interview_id)
            topics = {t.key: t for t in await self._topics(s, sess.id)}
            for upd in updates or []:
                row = topics.get(_slug(upd.get("key") or ""))
                if row is None:
                    continue
                if upd.get("title"):
                    row.title = upd["title"]
                if upd.get("why"):
                    row.why = upd["why"]
                if upd.get("priority"):
                    row.priority = service.normalize_priority(upd["priority"])
                if upd.get("status") in ("pending", "active", "covered", "dropped"):
                    row.status = upd["status"]
            await s.flush()
            topic_rows = await self._topics(s, sess.id)
            self._recompute(sess, topic_rows)
            await s.commit()
            return await self._state(s, sess.id)

    async def complete(self, interview_id: str) -> dict[str, Any]:
        async with self._sf() as s:
            sess = await self._load(s, interview_id)
            sess.status = "complete"
            await s.commit()
            return await self._state(s, sess.id)

    async def delete(self, interview_id: str) -> bool:
        async with self._sf() as s:
            try:
                sess = await self._load(s, interview_id)
            except InterviewNotFound:
                return False
            await s.delete(sess)
            await s.commit()
            return True

    async def state(self, interview_id: str) -> dict[str, Any]:
        async with self._sf() as s:
            await self._load(s, interview_id)
            return await self._state(s, interview_id)

    async def list(self, user_id: str | None = None) -> list[dict[str, Any]]:
        async with self._sf() as s:
            stmt = select(InterviewSession).order_by(InterviewSession.updated_at.desc())
            rows = (await s.execute(stmt)).scalars().all()
            return [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "goal": r.goal,
                    "status": r.status,
                    "coverage_pct": r.coverage_pct,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]

    async def brief(self, interview_id: str) -> str:
        async with self._sf() as s:
            sess = await self._load(s, interview_id)
            topics = await self._topics(s, sess.id)
            turns = await self._turns(s, sess.id)
            views = [_to_view(t) for t in topics]
            return service.render_brief(
                title=sess.title,
                goal=sess.goal,
                domain_brief=sess.domain_brief,
                topics=views,
                turns=[{"question": t.question, "answer": t.answer} for t in turns],
                coverage=sess.coverage_pct,
                ready=service.is_ready(
                    views, target_min=sess.target_min, target_pct=sess.target_pct
                ),
            )

    async def _state(self, s: AsyncSession, interview_id: Any) -> dict[str, Any]:
        sess = await self._load(s, str(interview_id))
        topics = await self._topics(s, sess.id)
        turns = await self._turns(s, sess.id)
        views = [_to_view(t) for t in topics]
        ready = service.is_ready(
            views, target_min=sess.target_min, target_pct=sess.target_pct
        )
        return {
            "id": str(sess.id),
            "title": sess.title,
            "goal": sess.goal,
            "domain_brief": sess.domain_brief,
            "status": sess.status,
            "target_min": sess.target_min,
            "target_pct": sess.target_pct,
            "coverage_pct": sess.coverage_pct,
            "ready": ready,
            "topics": [
                {
                    "key": t.key,
                    "title": t.title,
                    "description": t.description,
                    "why": t.why,
                    "priority": t.priority,
                    "status": t.status,
                    "coverage": t.coverage,
                    "notes": t.notes,
                    "origin": t.origin,
                    "sort": t.sort,
                }
                for t in topics
            ],
            "turns": [
                {
                    "seq": t.seq,
                    "question": t.question,
                    "answer": t.answer,
                    "constraints": t.constraints or [],
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in turns
            ],
        }
