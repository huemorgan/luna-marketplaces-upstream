"""Cloudflare plugin routes — webhook receiver + settings API.

Mounted at /api/p/plugin-cloudflare/
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from luna_sdk import PluginContext, get_current_user

import logging

log = logging.getLogger("plugin-cloudflare.routes")

router = APIRouter(prefix="/api/p/plugin-cloudflare", tags=["cloudflare"])

_ctx: PluginContext | None = None

_SETTINGS_DIR = Path(__file__).parent / "interface" / "webui" / "settings"


def init_routes(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


def register_routes(app, ctx: PluginContext) -> None:
    """Loader entry point. Using register_routes (instead of self-mounting in
    on_load) lets the core push these routes ahead of the SPA catch-all so
    /ui/settings/ and the connect/status APIs resolve correctly."""
    init_routes(ctx)
    app.include_router(router)


class _ConnectReq(BaseModel):
    api_token: str
    account_id: str


# --- Settings endpoints ---


@router.post("/connect")
async def connect(body: _ConnectReq, user=Depends(get_current_user)):
    """Store Cloudflare credentials in vault."""
    if _ctx is None or _ctx.vault is None:
        raise HTTPException(503, "Vault not available")
    await _ctx.vault.store_credential("plugin_cloudflare.api_token", body.api_token, kind="api_key")
    await _ctx.vault.store_credential("plugin_cloudflare.account_id", body.account_id, kind="api_key")
    return {"connected": True}


@router.post("/disconnect")
async def disconnect(user=Depends(get_current_user)):
    """Remove Cloudflare credentials from vault."""
    if _ctx is None or _ctx.vault is None:
        raise HTTPException(503, "Vault not available")
    await _ctx.vault.delete_credential("plugin_cloudflare.api_token")
    await _ctx.vault.delete_credential("plugin_cloudflare.account_id")
    return {"disconnected": True}


@router.get("/status")
async def status(user=Depends(get_current_user)):
    """Check connection status."""
    if _ctx is None or _ctx.vault is None:
        return {"connected": False}
    try:
        await _ctx.vault.get_credential("plugin_cloudflare.api_token")
        await _ctx.vault.get_credential("plugin_cloudflare.account_id")
        return {"connected": True}
    except KeyError:
        return {"connected": False}


# --- Settings UI (served as a themed iframe by the host) ---


@router.get("/ui/settings/")
async def settings_index():
    index = _SETTINGS_DIR / "index.html"
    if not index.exists():
        raise HTTPException(404, "settings UI not found")
    return FileResponse(str(index), headers={"Cache-Control": "no-cache"})


@router.get("/ui/settings/{path:path}")
async def settings_asset(path: str):
    target = (_SETTINGS_DIR / path).resolve()
    if not str(target).startswith(str(_SETTINGS_DIR.resolve())):
        raise HTTPException(403, "forbidden")
    if not target.exists() or target.is_dir():
        return FileResponse(str(_SETTINGS_DIR / "index.html"), headers={"Cache-Control": "no-cache"})
    return FileResponse(str(target), headers={"Cache-Control": "no-cache"})


# --- Webhook receiver ---

_EVENT_MAP: dict[str, str] = {
    "pages_deployment_success": "cloudflare.deploy.succeeded",
    "pages_deployment_failed": "cloudflare.deploy.failed",
    "workers_deployment_success": "cloudflare.deploy.succeeded",
    "workers_deployment_failed": "cloudflare.deploy.failed",
    "ssl_certificate_expiring": "cloudflare.ssl.expiring",
    "health_check_status_unhealthy": "cloudflare.healthcheck.failed",
    "health_check_status_healthy": "cloudflare.healthcheck.recovered",
}


@router.post("/webhook")
async def webhook(request: Request):
    """Receives Cloudflare notification webhooks and emits bus events."""
    if _ctx is None:
        raise HTTPException(503, "Plugin not initialized")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    alert_type = payload.get("alert_type", payload.get("data", {}).get("alert_type", ""))
    event_name = _EVENT_MAP.get(alert_type)

    if event_name:
        await _ctx.events.emit(event_name, payload)
        log.info("cf webhook: %s (alert_type=%s)", event_name, alert_type)
    else:
        log.debug("cf webhook unhandled: alert_type=%s", alert_type)

    return {"received": True, "event": event_name}
