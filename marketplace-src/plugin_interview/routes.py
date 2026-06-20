"""plugin-interview API routes — interviews browser (left-pane iframe).

Self-owned, mounted at /api/p/plugin-interview/* by the loader via
manifest.routes_module. Serves the read/manage endpoints plus the sidebar
pane UI (`/ui/`). Decoupled to `luna_sdk` — no `import luna.*`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from .store import InterviewNotFound, InterviewStore

_UI_DIR = Path(__file__).parent / "ui"


def register_routes(app, ctx):
    from luna_sdk import get_current_user

    store = InterviewStore(ctx.db_session_factory)
    router = APIRouter(prefix="/api/p/plugin-interview", tags=["interview"])

    @router.get("/interviews")
    async def list_interviews(user=Depends(get_current_user)):
        return await store.list()

    @router.get("/interviews/{interview_id}")
    async def get_interview(interview_id: str, user=Depends(get_current_user)):
        try:
            return await store.state(interview_id)
        except InterviewNotFound as e:
            raise HTTPException(404, "interview not found") from e

    @router.get("/interviews/{interview_id}/brief")
    async def get_brief(interview_id: str, user=Depends(get_current_user)):
        try:
            md = await store.brief(interview_id)
        except InterviewNotFound as e:
            raise HTTPException(404, "interview not found") from e
        return Response(content=md, media_type="text/markdown")

    @router.delete("/interviews/{interview_id}")
    async def delete_interview(interview_id: str, user=Depends(get_current_user)):
        ok = await store.delete(interview_id)
        if not ok:
            raise HTTPException(404, "interview not found")
        return {"deleted": True, "id": interview_id}

    # --- Sidebar pane UI (served as a full-pane iframe by the host) ---

    @router.get("/ui/")
    async def serve_ui_root():
        index = _UI_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index), headers={"Cache-Control": "no-cache"})
        return Response(content="<h1>plugin-interview UI not built</h1>", media_type="text/html")

    @router.get("/ui/{path:path}")
    async def serve_ui(path: str):
        if not path or path == "/":
            path = "index.html"
        target = (_UI_DIR / path).resolve()
        if not str(target).startswith(str(_UI_DIR.resolve())):
            raise HTTPException(403, "Forbidden")
        if not target.exists() or target.is_dir():
            index = _UI_DIR / "index.html"
            if index.exists():
                return FileResponse(str(index), headers={"Cache-Control": "no-cache"})
            raise HTTPException(404, "Not found")
        return FileResponse(str(target), headers={"Cache-Control": "no-cache"})

    app.include_router(router)
