"""plugin-connectors API routes — provider key, catalog, app lifecycle, events ingress."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .protocol import ConnectorProviderError

log = logging.getLogger("plugin-connectors.routes")

_SETTINGS_DIR = Path(__file__).parent / "interface" / "webui" / "settings"

# 007.001: writes go to the canonical name; the legacy name is still deleted
# on disconnect so old installs fully detach.
from . import VAULT_COMPOSIO_CANONICAL, VAULT_COMPOSIO_KEY  # noqa: E402
from .state import get_plugin  # noqa: E402


class _KeyReq(BaseModel):
    api_key: str


class _ConnectKeyReq(BaseModel):
    # Field name → value, per the toolkit's auth field spec (e.g. firecrawl:
    # {"generic_api_key": "fc-…", "full": "https://api.firecrawl.dev/v1"}).
    credentials: dict[str, str]


class _ExposureReq(BaseModel):
    agent: bool | None = None
    triggers: bool | None = None


def register_routes(app, ctx):
    from luna_sdk import get_current_user

    router = APIRouter(prefix="/api/p/plugin-connectors", tags=["connectors"])

    def _vault():
        if ctx.vault is None:
            raise HTTPException(503, "Vault not available")
        return ctx.vault

    def _plugin():
        plug = get_plugin()
        if plug is None:
            raise HTTPException(503, "plugin-connectors not loaded")
        return plug

    # Restore tools/skills for connected apps once uvicorn's real event loop
    # is running (plugin on_load happens in a throwaway bootstrap loop).
    async def _restore_on_startup() -> None:
        import asyncio

        async def _go() -> None:
            try:
                await _plugin().restore_connected_apps()
            except Exception as e:  # noqa: BLE001
                log.warning("connectors: startup restore failed error=%s", e)

        asyncio.create_task(_go())

    # FastAPI ≥0.136 dropped add_event_handler; the Starlette router list remains.
    app.router.on_startup.append(_restore_on_startup)

    # -- provider --------------------------------------------------------

    @router.get("/status")
    async def status(user=Depends(get_current_user)):
        plug = _plugin()
        return {
            "configured": plug.configured,
            "providers": [plug.composio_status()],
            "apps": plug.app_states(),
        }

    @router.post("/provider/composio/key")
    async def set_key(body: _KeyReq, user=Depends(get_current_user)):
        from .providers.composio import ComposioProvider

        key = body.api_key.strip()
        if not key:
            raise HTTPException(400, "Empty API key")
        # Validate through the gateway when one is configured — a tenant
        # token only authenticates at the proxy, not at real Composio.
        base_url = (ctx.get_env("LUNA_COMPOSIO_BASE_URL") or "").strip()
        if base_url:
            candidate = ComposioProvider(key, base_url=base_url, auth_mode="gateway")
        else:
            candidate = ComposioProvider(key)
        ok = await candidate.validate()
        await candidate.close()
        if not ok:
            detail = "Invalid Composio API key"
            if base_url:
                detail += f" (validated via gateway {base_url})"
            raise HTTPException(400, detail)

        # Storing emits credential.stored → the plugin rebuilds the provider
        # through the full vault → env chain (007.001).
        await _vault().store_credential(VAULT_COMPOSIO_CANONICAL, key, kind="api_key")
        plug = _plugin()
        return {"configured": "composio" in plug._providers}

    @router.post("/provider/composio/disconnect")
    async def remove_key(user=Depends(get_current_user)):
        plug = _plugin()
        for slug in [a["slug"] for a in plug.app_states()]:
            plug.unregister_app_tools(slug)
        # Delete BOTH vault names; credential.deleted re-runs _init_composio,
        # which falls back to the env key when the host provides one (a BYOK
        # disconnect on a managed instance reverts to the hosting plan's key).
        vault = _vault()
        await vault.delete_credential(VAULT_COMPOSIO_CANONICAL)
        await vault.delete_credential(VAULT_COMPOSIO_KEY)
        return {"configured": "composio" in plug._providers}

    # -- catalog ---------------------------------------------------------

    @router.get("/catalog")
    async def catalog(search: str = "", limit: int = 24, user=Depends(get_current_user)):
        plug = _plugin()
        provider = plug.default_provider()
        if provider is None:
            raise HTTPException(400, "No provider configured")
        try:
            apps = await provider.list_apps(search=search, limit=limit)
        except ConnectorProviderError as e:
            raise HTTPException(502, str(e)) from e
        state = {a["slug"]: a for a in plug.app_states()}
        return [
            {
                "slug": a.slug,
                "name": a.name,
                "description": a.description,
                "logo": a.logo,
                "no_auth": a.no_auth,
                "tools_count": a.tools_count,
                "triggers_count": a.triggers_count,
                "connected": bool(state.get(a.slug, {}).get("connected")),
                "enabled_agent": bool(state.get(a.slug, {}).get("enabled_agent")),
                "enabled_triggers": bool(state.get(a.slug, {}).get("enabled_triggers")),
            }
            for a in apps
        ]

    # -- app lifecycle ----------------------------------------------------

    @router.post("/apps/{slug}/connect")
    async def connect(slug: str, user=Depends(get_current_user)):
        plug = _plugin()
        try:
            return await plug.connect_app(slug.lower())
        except ConnectorProviderError as e:
            raise HTTPException(502, str(e)) from e

    @router.post("/apps/{slug}/connect-key")
    async def connect_key(
        slug: str, body: _ConnectKeyReq, user=Depends(get_current_user)
    ):
        """Complete a custom-auth (API-key) connection. Credentials go straight
        to the provider — never logged, never seen by the LLM."""
        creds = {k: v for k, v in (body.credentials or {}).items() if v != ""}
        if not creds:
            raise HTTPException(400, "No credentials provided")
        plug = _plugin()
        try:
            return await plug.connect_app_with_key(slug.lower(), creds)
        except ConnectorProviderError as e:
            raise HTTPException(502, str(e)) from e

    @router.post("/apps/{slug}/refresh")
    async def refresh(slug: str, user=Depends(get_current_user)):
        plug = _plugin()
        try:
            return await plug.refresh_app(slug.lower())
        except ConnectorProviderError as e:
            raise HTTPException(502, str(e)) from e

    @router.post("/apps/{slug}/disconnect")
    async def disconnect(slug: str, user=Depends(get_current_user)):
        plug = _plugin()
        await plug.disconnect_app(slug.lower())
        return {"connected": False}

    @router.get("/apps/{slug}/account")
    async def account(slug: str, user=Depends(get_current_user)):
        """Identifying details (email/username, status, connect date) of the
        connected account — no keys or tokens."""
        plug = _plugin()
        try:
            return await plug.account_details(slug.lower())
        except ConnectorProviderError as e:
            raise HTTPException(404, str(e)) from e

    @router.post("/apps/{slug}/exposure")
    async def exposure(slug: str, body: _ExposureReq, user=Depends(get_current_user)):
        plug = _plugin()
        try:
            app_state = await plug.set_exposure(slug.lower(), body.agent, body.triggers)
        except ConnectorProviderError as e:
            raise HTTPException(404, str(e)) from e
        return {
            "slug": slug.lower(),
            "enabled_agent": app_state.get("enabled_agent", False),
            "enabled_triggers": app_state.get("enabled_triggers", False),
        }

    # -- events ingress (provider webhooks; no user auth — signature instead) --

    @router.post("/events/{provider}")
    async def events(provider: str, request: Request):
        if provider != "composio":
            raise HTTPException(404, f"Unknown provider: {provider}")
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(payload, dict) or len(str(payload)) > 200_000:
            raise HTTPException(400, "Bad payload")
        plug = _plugin()
        event_name = await plug.handle_provider_event(provider, payload)
        return {"ok": True, "event": event_name}

    # -- Settings UI (served as a themed iframe by the host) --------------

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
