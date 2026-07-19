"""Persistent owner grants — currently one key: ``auto_approve_agent_goals``.

The grant store is append-only history: an active grant is a row with
``revoked_at IS NULL``; revoking stamps the timestamp; re-granting inserts a
new row. The Grants UI (phase 05) reads the same table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from .models import GrantRow

AUTO_APPROVE_AGENT_GOALS = "auto_approve_agent_goals"

KNOWN_KEYS = (AUTO_APPROVE_AGENT_GOALS,)


def _grant_dict(g: GrantRow) -> dict[str, Any]:
    return {
        "id": str(g.id),
        "key": g.key,
        "granted_by": g.granted_by,
        "granted_at": g.granted_at.isoformat() if g.granted_at else None,
        "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
        "active": g.revoked_at is None,
    }


class GrantStore:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def is_active(self, key: str) -> bool:
        async with self._sf() as s:
            row = (
                await s.execute(
                    select(GrantRow).where(GrantRow.key == key, GrantRow.revoked_at.is_(None))
                )
            ).scalars().first()
            return row is not None

    async def grant(self, key: str, *, granted_by: str = "owner") -> dict[str, Any]:
        if key not in KNOWN_KEYS:
            raise ValueError(f"unknown grant key {key!r} — known: {list(KNOWN_KEYS)}")
        async with self._sf() as s:
            existing = (
                await s.execute(
                    select(GrantRow).where(GrantRow.key == key, GrantRow.revoked_at.is_(None))
                )
            ).scalars().first()
            if existing is not None:
                return _grant_dict(existing)
            row = GrantRow(key=key, granted_by=granted_by)
            s.add(row)
            await s.commit()
            return _grant_dict(row)

    async def revoke(self, key: str) -> dict[str, Any]:
        async with self._sf() as s:
            row = (
                await s.execute(
                    select(GrantRow).where(GrantRow.key == key, GrantRow.revoked_at.is_(None))
                )
            ).scalars().first()
            if row is None:
                raise LookupError(f"no active grant for {key!r}")
            row.revoked_at = datetime.now(UTC)
            await s.commit()
            return _grant_dict(row)

    async def list(self) -> list[dict[str, Any]]:
        async with self._sf() as s:
            rows = (
                await s.execute(select(GrantRow).order_by(GrantRow.granted_at.desc()))
            ).scalars().all()
            return [_grant_dict(g) for g in rows]
