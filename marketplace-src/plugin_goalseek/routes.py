"""REST API + pane UI for plugin-goalseek.

Mounted at /api/p/plugin-goalseek/. Two routers, playbooks pattern:
- ``router``   — authed JSON API for the Goals pane.
- ``ui_router`` — UNAUTHED static files for the iframe (the app inside
  authenticates every API call with the token the Shell posts in).

Approvals are NOT proxied here: the pane calls the core plugin-approvals
REST directly (same origin, same token) — one approval engine, one API.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from luna_sdk import get_current_user

from . import tuning
from .models import EventRow, GoalRow, PolicyRow, StepRow, WaitRow
from .policy import FAMILIES

router = APIRouter(
    prefix="/api/p/plugin-goalseek",
    tags=["goalseek"],
    dependencies=[Depends(get_current_user)],
)

_store: Any = None
_waits: Any = None
_settings: Any = None
_grants: Any = None
_runtime: Any = None
_tools: Any = None
_sf: Any = None
_knowledge: Any = None


def init_routes(*, store, waits, settings, grants, runtime=None,
                tool_registry=None, session_factory=None, knowledge=None) -> None:
    global _store, _waits, _settings, _grants, _runtime, _tools, _sf, _knowledge
    _store = store
    _waits = waits
    _settings = settings
    _grants = grants
    _runtime = runtime
    _tools = tool_registry
    _sf = session_factory
    _knowledge = knowledge


# ---- Pane UI (iframe): unauthed static ----

ui_router = APIRouter(prefix="/api/p/plugin-goalseek", tags=["goalseek-ui"])

_UI_DIR = Path(__file__).parent / "ui"
_NO_CACHE = {"Cache-Control": "no-cache"}


def _versioned_index() -> Response:
    """index.html with ?v=<plugin version> stamped on asset URLs (edge caches
    hold hashed assets; the version query guarantees a fresh fetch per release)."""
    try:
        import tomllib

        _v = str(
            tomllib.loads(
                (Path(__file__).parent / "luna-plugin.toml").read_text()
            )["version"]
        )
    except Exception:  # noqa: BLE001
        _v = "0"
    html = (_UI_DIR / "index.html").read_text()
    html = html.replace('.js"', f'.js?v={_v}"').replace('.css"', f'.css?v={_v}"')
    return Response(content=html, media_type="text/html", headers=_NO_CACHE)


@ui_router.get("/ui/")
async def serve_ui_root():
    if (_UI_DIR / "index.html").exists():
        return _versioned_index()
    return Response(content="<h1>plugin-goalseek UI not built</h1>", media_type="text/html")


@ui_router.get("/ui/{path:path}")
async def serve_ui(path: str):
    if not path or path == "/":
        path = "index.html"
    target = (_UI_DIR / path).resolve()
    if not str(target).startswith(str(_UI_DIR.resolve())):
        raise HTTPException(403, "Forbidden")
    if not target.exists():
        if (_UI_DIR / "index.html").exists():
            return _versioned_index()
        raise HTTPException(404, "Not found")
    return FileResponse(str(target), headers=_NO_CACHE)


def register_routes(app: Any, ctx: Any) -> None:
    app.include_router(router)
    app.include_router(ui_router)


# ---- helpers ----------------------------------------------------------------


def _gid(goal_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(goal_id))
    except ValueError:
        raise HTTPException(404, f"no goal {goal_id}") from None


async def _gate_stats_for(goal_id: uuid.UUID, limit: int = 200) -> dict[str, Any]:
    async with _sf() as s:
        events = (
            await s.execute(
                select(EventRow)
                .where(EventRow.goal_id == goal_id)
                .order_by(EventRow.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    return tuning.gate_stats([{"kind": e.kind, "payload": e.payload} for e in events])


def _progress(steps: list[dict]) -> dict[str, Any]:
    live = [s for s in steps if s["status"] != "ghost"]
    done = [s for s in live if s["status"] == "done"]
    return {
        "steps_total": len(live),
        "steps_done": len(done),
        "pct": round(100 * len(done) / len(live)) if live else 0,
    }


# ---- board / detail ----------------------------------------------------------


@router.get("/goals")
async def board():
    goals = await _store.list(include_closed=True)
    async with _sf() as s:
        step_rows = (await s.execute(select(StepRow))).scalars().all()
        open_waits = (
            await s.execute(select(WaitRow).where(WaitRow.status == "open"))
        ).scalars().all()
    steps_by_goal: dict[str, list[dict]] = {}
    for r in step_rows:
        steps_by_goal.setdefault(str(r.goal_id), []).append(
            {"status": r.status}
        )
    waits_by_goal: dict[str, int] = {}
    for w in open_waits:
        waits_by_goal[str(w.goal_id)] = waits_by_goal.get(str(w.goal_id), 0) + 1
    out = []
    for g in goals:
        stats = await _gate_stats_for(uuid.UUID(g["id"]), limit=100)
        out.append({
            **g,
            **_progress(steps_by_goal.get(g["id"], [])),
            "open_waits": waits_by_goal.get(g["id"], 0),
            "gate": stats,
        })
    return {"goals": out}


@router.get("/goals/{goal_id}")
async def goal_detail(goal_id: str):
    gid = _gid(goal_id)
    try:
        goal = await _store.get(goal_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    async with _sf() as s:
        waits = (
            await s.execute(
                select(WaitRow).where(WaitRow.goal_id == gid)
                .order_by(WaitRow.created_at.desc()).limit(20)
            )
        ).scalars().all()
        policies = (
            await s.execute(
                select(PolicyRow).where(
                    (PolicyRow.goal_id == gid) | (PolicyRow.goal_id.is_(None))
                )
            )
        ).scalars().all()
    goal["waits"] = [
        {
            "id": str(w.id), "kind": w.kind, "description": w.description,
            "status": w.status, "params": w.params or {},
            "timeout_at": w.timeout_at.isoformat() if w.timeout_at else None,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in waits
    ]
    goal["policies"] = [
        {
            "id": str(p.id), "family": p.family, "params": p.params or {},
            "goal_id": str(p.goal_id) if p.goal_id else None,
            "enabled": p.enabled, "created_by": p.created_by,
        }
        for p in policies
    ]
    goal["gate"] = await _gate_stats_for(gid)
    goal.update(_progress(goal.get("steps") or []))
    goal["knowledge"] = await _knowledge_info(goal_id)
    return goal


async def _knowledge_info(goal_id: str) -> dict[str, Any]:
    """Where this goal's narrative lives (phase 06): the wiki page when a
    wiki backend is active, plus any local fallback notes."""
    if _knowledge is None:
        return {"backend": "none", "notes": []}
    from .knowledge import goal_page_slug

    try:
        be = await _knowledge.backend()
        notes = await _knowledge.read_notes(goal_id)
    except Exception:  # noqa: BLE001 — the pane must render without a wiki
        return {"backend": "none", "notes": []}
    return {
        "backend": be["backend"],
        "wiki": be["wiki"],
        "page": goal_page_slug(goal_id) if be["backend"] == "wiki" else None,
        "notes": notes,
    }


@router.get("/goals/{goal_id}/events")
async def goal_events(goal_id: str, after: Optional[str] = None, limit: int = 300):
    """Ascending evidence trail — also the night-shift replay frame source."""
    gid = _gid(goal_id)
    q = select(EventRow).where(EventRow.goal_id == gid).order_by(EventRow.created_at)
    if after:
        try:
            ts = datetime.fromisoformat(after)
        except ValueError:
            raise HTTPException(400, f"invalid 'after' timestamp: {after}") from None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        q = q.where(EventRow.created_at > ts)
    async with _sf() as s:
        rows = (await s.execute(q.limit(min(int(limit), 1000)))).scalars().all()
    return {
        "events": [
            {"id": str(e.id), "kind": e.kind, "payload": e.payload,
             "at": e.created_at.isoformat()}
            for e in rows
        ]
    }


class WaitCancel(BaseModel):
    note: str = ""


@router.post("/waits/{wait_id}/cancel")
async def cancel_wait(wait_id: str, body: WaitCancel | None = None):
    try:
        out = await _waits.cancel(wait_id, note=(body.note if body else "") or "cancelled from the Goals pane")
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    if _runtime is not None and out.get("goal_id"):
        try:
            await _runtime.sync(out["goal_id"])
        except Exception:  # noqa: BLE001
            pass
    return out


# ---- policies ------------------------------------------------------------------


@router.get("/policies")
async def list_policies():
    async with _sf() as s:
        rows = (await s.execute(select(PolicyRow).order_by(PolicyRow.created_at))).scalars().all()
    return {
        "policies": [
            {
                "id": str(p.id), "family": p.family, "params": p.params or {},
                "goal_id": str(p.goal_id) if p.goal_id else None,
                "enabled": p.enabled, "created_by": p.created_by,
            }
            for p in rows
        ],
        "families": list(FAMILIES),
    }


class PolicyUpsert(BaseModel):
    id: Optional[str] = None
    family: str
    params: dict = {}
    goal_id: Optional[str] = None
    enabled: bool = True


@router.post("/policies")
async def upsert_policy(body: PolicyUpsert):
    if body.family not in FAMILIES:
        raise HTTPException(400, f"unknown family '{body.family}' (valid: {list(FAMILIES)})")
    async with _sf() as s:
        if body.id:
            row = await s.get(PolicyRow, uuid.UUID(body.id))
            if row is None:
                raise HTTPException(404, f"no policy {body.id}")
            row.family = body.family
            row.params = body.params
            row.goal_id = uuid.UUID(body.goal_id) if body.goal_id else None
            row.enabled = body.enabled
        else:
            row = PolicyRow(
                family=body.family, params=body.params,
                goal_id=uuid.UUID(body.goal_id) if body.goal_id else None,
                enabled=body.enabled, created_by="owner",
            )
            s.add(row)
        await s.flush()
        out = {"id": str(row.id), "family": row.family, "params": row.params,
               "goal_id": str(row.goal_id) if row.goal_id else None, "enabled": row.enabled}
        await s.commit()
    return out


@router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: str):
    async with _sf() as s:
        row = await s.get(PolicyRow, uuid.UUID(policy_id))
        if row is None:
            raise HTTPException(404, f"no policy {policy_id}")
        await s.delete(row)
        await s.commit()
    return {"ok": True, "id": policy_id}


# ---- settings / grants ------------------------------------------------------------


def _integrations() -> dict[str, bool]:
    def _has(tool: str) -> bool:
        if _tools is None:
            return False
        try:
            return _tools.get(tool) is not None
        except (KeyError, AttributeError):
            return False

    return {
        "scheduler": _has("trigger_create"),
        "playbooks": _has("playbook_run"),
        "wiki": _has("wiki_read") or _has("wiki_search"),
        "curiosity": _has("mission_list") or _has("curiosity_status"),
    }


@router.get("/settings")
async def get_settings():
    from .settings import FIELD_SCHEMA

    return {
        "values": await _settings.get_all(),
        "schema": FIELD_SCHEMA,
        "integrations": _integrations(),
        "grants": await _grants.list(),
    }


class SettingsPut(BaseModel):
    changes: dict


@router.put("/settings")
async def put_settings(body: SettingsPut):
    try:
        values = await _settings.set_many(body.changes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"values": values}


@router.post("/grants/{key}/revoke")
async def revoke_grant(key: str):
    try:
        return await _grants.revoke(key)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


# ---- outcomes ------------------------------------------------------------------


@router.get("/outcomes")
async def outcomes():
    async with _sf() as s:
        rows = (
            await s.execute(
                select(GoalRow).where(GoalRow.stage == "closed")
                .order_by(GoalRow.updated_at.desc())
            )
        ).scalars().all()
    out = []
    for g in rows:
        stats = await _gate_stats_for(g.id)
        out.append({
            "id": str(g.id),
            "statement": g.statement,
            "outcome": g.outcome,
            "outcome_label": g.outcome_label,
            "reason": (g.outcome_reason or {}).get("summary") if g.outcome_reason else None,
            "closed_at": g.updated_at.isoformat() if g.updated_at else None,
            "gate": stats,
        })
    return {"outcomes": out}


# ---- live stream (SSE) -----------------------------------------------------------


STREAM_POLL_S = 1.5
STREAM_MAX_S = 3600  # the pane reconnects; never hold a socket forever


@router.get("/stream")
async def stream():
    """New goalseek events as SSE — the pane's live pulse. Plain DB tailing:
    survives any process topology and needs no bus wiring."""

    async def _gen():
        last = datetime.now(UTC)
        started = datetime.now(UTC)
        yield "event: hello\ndata: {}\n\n"
        while (datetime.now(UTC) - started).total_seconds() < STREAM_MAX_S:
            async with _sf() as s:
                rows = (
                    await s.execute(
                        select(EventRow).where(EventRow.created_at > last)
                        .order_by(EventRow.created_at).limit(200)
                    )
                ).scalars().all()
            for e in rows:
                at = e.created_at if e.created_at.tzinfo else e.created_at.replace(tzinfo=UTC)
                last = max(last, at)
                data = json.dumps({
                    "id": str(e.id), "goal_id": str(e.goal_id), "kind": e.kind,
                    "payload": e.payload, "at": at.isoformat(),
                })
                yield f"event: goal\ndata: {data}\n\n"
            await asyncio.sleep(STREAM_POLL_S)

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
