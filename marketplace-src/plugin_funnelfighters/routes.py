"""plugin-funnelfighters API routes — connect, disconnect, status, settings UI.

Stores the API key + org ID in the vault and (re)builds the plugin's live
client so the agent's tools work immediately after the user connects, without
a server restart. Mirrors the plugin-render/monday connect/disconnect/status
shape, decoupled to `luna_sdk` + `ctx.vault` + a module-level client singleton
(``state.py``) so it runs identically from a managed dir.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .client import FFClient
from .config import FF_DEFAULT_BASE_URL, FF_VAULT_KEY_API, FF_VAULT_KEY_ORG
from .state import get_client, set_client

log = logging.getLogger("plugin-funnelfighters.routes")

_SETTINGS_DIR = Path(__file__).parent / "interface" / "webui" / "settings"


class _ConnectReq(BaseModel):
    api_key: str
    org_id: str


class _StatusResp(BaseModel):
    connected: bool
    org_id: str | None = None


def register_routes(app, ctx):
    from luna_sdk import get_current_user

    router = APIRouter(prefix="/api/p/plugin-funnelfighters", tags=["funnelfighters"])

    def _vault():
        vault = ctx.vault
        if vault is None:
            raise HTTPException(503, "Vault not available")
        return vault

    @router.post("/connect")
    async def connect(body: _ConnectReq, user=Depends(get_current_user)):
        api_key = body.api_key.strip()
        org_id = body.org_id.strip()
        if not api_key or not org_id:
            raise HTTPException(400, "Both API key and org ID are required")

        client = FFClient(base_url=FF_DEFAULT_BASE_URL, api_key=api_key, org_id=org_id)
        try:
            await client.get("/api/home/summary")
        except Exception as e:  # noqa: BLE001
            await client.close()
            raise HTTPException(400, f"Could not connect with those credentials: {e}") from e
        finally:
            await client.close()

        vault = _vault()
        await vault.store_credential(FF_VAULT_KEY_API, api_key, kind="api_key")
        await vault.store_credential(FF_VAULT_KEY_ORG, org_id, kind="config")

        existing = get_client()
        if existing is not None:
            await existing.close()
        set_client(FFClient(base_url=FF_DEFAULT_BASE_URL, api_key=api_key, org_id=org_id))

        return {"connected": True, "org_id": org_id}

    @router.post("/disconnect")
    async def disconnect(user=Depends(get_current_user)):
        vault = _vault()
        for key in (FF_VAULT_KEY_API, FF_VAULT_KEY_ORG):
            try:
                await vault.delete_credential(key)
            except KeyError:
                pass

        existing = get_client()
        if existing is not None:
            await existing.close()
            set_client(None)

        return {"connected": False}

    @router.get("/status", response_model=_StatusResp)
    async def status(user=Depends(get_current_user)):
        vault = _vault()
        try:
            await vault.get_credential(FF_VAULT_KEY_API)
        except KeyError:
            return _StatusResp(connected=False)

        try:
            org_id = (await vault.get_credential(FF_VAULT_KEY_ORG)).value
        except KeyError:
            return _StatusResp(connected=False)

        return _StatusResp(connected=True, org_id=org_id)

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

    app.include_router(router)
