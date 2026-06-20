"""recall_conversation — verbatim message retrieval for the agent (008.002).

Fully decoupled (008.5/phase11): reads conversation history through the
sanctioned SDK surface — ``ctx.conversations`` (read-only) and
``ctx.current_conversation_id`` (E6) — and imports nothing from ``luna.*``.
Single-owner install → all conversations belong to the owner; the query still
scopes by conversation and is ready for a real ``user_id`` filter if multi-user
lands.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

# Roles that count as real conversation content (skip tool-call/tool-result rows
# unless explicitly requested).
_CONTENT_ROLES = ("user", "assistant")


def _as_uuid(value: str) -> _uuid.UUID | None:
    try:
        return _uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def make_recall_handler(ctx: Any):
    async def recall_conversation(
        query: str | None = None,
        scope: str = "current",
        conversation_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
        order: str = "asc",
        include_tools: bool = False,
    ) -> dict[str, Any]:
        offset = max(0, int(offset or 0))
        roles = None if include_tools else _CONTENT_ROLES

        # Resolve target conversations.
        if conversation_id:
            cid = _as_uuid(conversation_id)
            if cid is None:
                return {"error": f"invalid conversation_id {conversation_id!r}"}
            target_ids: list[_uuid.UUID] = [cid]
        elif scope == "all":
            convs = await ctx.conversations.list()
            target_ids = [c.id for c in convs]
        else:  # current
            cur = ctx.current_conversation_id
            if cur is None:
                return {
                    "error": (
                        "no current conversation in context — pass an explicit "
                        "conversation_id or use scope='all'."
                    )
                }
            target_ids = [cur]

        if not target_ids:
            return {"messages": [], "count": 0}

        msgs = await ctx.conversations.messages(
            target_ids,
            roles=roles,
            query=query,
            order=order,
            offset=offset,
            limit=limit,
        )

        out = []
        for i, m in enumerate(msgs):
            out.append(
                {
                    "conversation_id": str(m.conversation_id),
                    "conversation_title": m.conversation_title,
                    "seq": offset + i + 1,
                    "role": m.role,
                    "author": "you" if m.role == "user" else "agent",
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "content": m.content or "",
                }
            )
        return {"messages": out, "count": len(out)}

    return recall_conversation
