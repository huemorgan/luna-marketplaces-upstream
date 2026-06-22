"""Composio driver — implements ConnectorProvider over the Composio v3 REST API.

Validated against the live API (Jun 2026):
  GET  /api/v3/toolkits                     catalog (slug, name, meta.logo, no_auth, ...)
  GET  /api/v3/tools?toolkit_slug=X         tool schemas (input_parameters, tags)
  POST /api/v3/auth_configs                 create Composio-managed auth config
  POST /api/v3/connected_accounts/link      returns redirect_url for end-user OAuth
  GET  /api/v3/connected_accounts/{id}      account status
  POST /api/v3/tools/execute/{slug}         execute (no_auth toolkits need no account)

Auth modes:
  api_key  — BYO key (OSS), stored in vault
  gateway  — base URL + workspace token injected by luna-service (cloud); same
             wire protocol, different base/credential. The gateway holds the
             real Composio key; it never exists on this instance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..protocol import (
    AppInfo,
    AuthField,
    AuthInitiation,
    ConnectorProviderError,
    ProviderToolDef,
)

log = logging.getLogger("plugin-connectors.composio")

DEFAULT_BASE = "https://backend.composio.dev/api/v3"
USER_ID = "default"  # Luna is single-user

_RETRYABLE = {429, 500, 502, 503, 504}

# Field names/types that signal a secret even when the provider omits is_secret.
_SECRET_HINTS = ("key", "token", "secret", "password", "passwd", "pwd")


def _looks_secret(name: str, ftype: str) -> bool:
    low = f"{name} {ftype}".lower()
    return any(h in low for h in _SECRET_HINTS)


def _parse_auth(detail: dict[str, Any]) -> tuple[str, list[AuthField]]:
    """Pick the auth mode + the fields a user must supply, from a toolkit's
    `auth_config_details`. Prefers managed OAuth when offered (existing happy
    path); otherwise the first non-NO_AUTH mode (custom auth). Returns
    ("", []) when the toolkit needs no user-supplied fields (no-auth/managed)."""
    details = detail.get("auth_config_details") or []
    if not details:
        return "", []

    def _mode(d: dict[str, Any]) -> str:
        return (d.get("mode") or "").upper()

    oauth = next((d for d in details if _mode(d).startswith("OAUTH")), None)
    if oauth is not None:
        return _mode(oauth), []  # managed redirect; no fields collected here

    custom = next((d for d in details if _mode(d) not in ("", "NO_AUTH")), None)
    if custom is None:
        return "", []

    init = (custom.get("fields") or {}).get("connected_account_initiation") or {}
    fields: list[AuthField] = []
    for spec, required in (
        (init.get("required") or [], True),
        (init.get("optional") or [], False),
    ):
        for f in spec:
            name = f.get("name") or ""
            if not name:
                continue
            ftype = f.get("type") or "string"
            fields.append(
                AuthField(
                    name=name,
                    label=f.get("displayName") or name,
                    type=ftype,
                    required=bool(f.get("required", required)),
                    secret=bool(f.get("is_secret")) or _looks_secret(name, ftype),
                    default=str(f.get("default") or ""),
                    description=(f.get("description") or "")[:300],
                )
            )
    if not fields:
        # The toolkit declares a custom scheme but exposes no field spec —
        # fall back to a single API-key field so the user still has a path.
        fields = [
            AuthField(name="api_key", label="API Key", secret=True, required=True)
        ]
    return _mode(custom), fields


class ComposioProvider:
    name = "composio"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE,
        auth_mode: str = "api_key",
    ) -> None:
        self._auth_mode = auth_mode
        self._api_key = api_key
        self._base_url = base_url
        self._http = self._make_client()
        self._client_loop: asyncio.AbstractEventLoop | None = None

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"x-api-key": self._api_key},
            timeout=30.0,
        )

    def _client(self) -> httpx.AsyncClient:
        """Loop-safe client. `luna serve` bootstraps plugins in a temporary
        event loop and then runs uvicorn in a fresh one; httpx pools
        connections per-loop, so a client used across that boundary raises
        'Event loop is closed'. Recreate the client when the loop changes."""
        loop = asyncio.get_running_loop()
        if self._client_loop is not loop:
            if self._client_loop is not None:
                old = self._http
                self._http = self._make_client()
                # Old pool belongs to a dead loop; closing it there is
                # impossible — drop the reference and let GC reap sockets.
                del old
            self._client_loop = loop
        return self._http

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._client().request(method, path, **kwargs)
            except httpx.HTTPError as e:
                last_exc = e
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code in _RETRYABLE and attempt < 2:
                retry_after = float(resp.headers.get("retry-after", 0) or 0)
                await asyncio.sleep(max(retry_after, 0.5 * (attempt + 1)))
                continue
            if resp.status_code >= 400:
                detail = resp.text[:500]
                raise ConnectorProviderError(
                    f"composio {method} {path} -> {resp.status_code}: {detail}"
                )
            return resp.json()
        raise ConnectorProviderError(f"composio {method} {path} failed: {last_exc}")

    # -- catalog ---------------------------------------------------------

    async def validate(self) -> bool:
        try:
            await self._request("GET", "/toolkits", params={"limit": 1})
            return True
        except ConnectorProviderError:
            return False

    @staticmethod
    def _to_app(item: dict[str, Any]) -> AppInfo:
        meta = item.get("meta") or {}
        # List endpoint ships a top-level `no_auth`; the detail endpoint
        # instead exposes auth_config_details[*].mode == "NO_AUTH".
        no_auth = bool(item.get("no_auth"))
        if not no_auth:
            modes = [
                (d.get("mode") or "").upper()
                for d in (item.get("auth_config_details") or [])
            ]
            no_auth = bool(modes) and all(m == "NO_AUTH" for m in modes)
        # Auth mode + fields only come from the detail endpoint
        # (auth_config_details). The list endpoint omits them → ("", []).
        auth_mode, auth_fields = _parse_auth(item)
        return AppInfo(
            slug=item.get("slug", ""),
            name=item.get("name", item.get("slug", "")),
            description=(meta.get("description") or "")[:300],
            logo=meta.get("logo"),
            no_auth=no_auth,
            tools_count=int(meta.get("tools_count") or 0),
            triggers_count=int(meta.get("triggers_count") or 0),
            categories=[c.get("name", "") for c in (meta.get("categories") or [])],
            auth_mode=auth_mode,
            auth_fields=auth_fields,
        )

    async def list_apps(self, search: str = "", limit: int = 50) -> list[AppInfo]:
        params: dict[str, Any] = {"limit": limit}
        if search:
            params["search"] = search
        data = await self._request("GET", "/toolkits", params=params)
        return [self._to_app(item) for item in data.get("items", [])]

    async def get_app(self, slug: str) -> AppInfo | None:
        try:
            data = await self._request("GET", f"/toolkits/{slug}")
        except ConnectorProviderError:
            # fall back to search — some slugs 404 on the direct endpoint
            for app in await self.list_apps(search=slug, limit=10):
                if app.slug == slug:
                    return app
            return None
        return self._to_app(data)

    async def list_tools(self, app: str, limit: int = 60) -> list[ProviderToolDef]:
        data = await self._request(
            "GET", "/tools", params={"toolkit_slug": app, "limit": limit}
        )
        out: list[ProviderToolDef] = []
        for item in data.get("items", []):
            tags = item.get("tags") or []
            params = item.get("input_parameters") or {"type": "object", "properties": {}}
            out.append(
                ProviderToolDef(
                    slug=item.get("slug", ""),
                    name=item.get("name", item.get("slug", "")),
                    description=(item.get("description") or "")[:500],
                    parameters=params,
                    destructive="destructiveHint" in tags,
                    read_only="readOnlyHint" in tags,
                )
            )
        return out

    # -- connections -----------------------------------------------------

    async def initiate_connection(self, app: str) -> AuthInitiation:
        cfg = await self._request(
            "POST",
            "/auth_configs",
            json={
                "toolkit": {"slug": app},
                "auth_config": {"type": "use_composio_managed_auth"},
            },
        )
        auth_config_id = (cfg.get("auth_config") or {}).get("id")
        if not auth_config_id:
            raise ConnectorProviderError(f"composio: no auth_config id for {app}")
        link = await self._request(
            "POST",
            "/connected_accounts/link",
            json={"auth_config_id": auth_config_id, "user_id": USER_ID},
        )
        return AuthInitiation(
            redirect_url=link.get("redirect_url", ""),
            connected_account_id=link.get("connected_account_id", ""),
            auth_config_id=auth_config_id,
        )

    async def initiate_custom_connection(
        self, app: str, credentials: dict[str, str]
    ) -> AuthInitiation:
        """Connect an API-key / custom-auth toolkit with user-supplied
        credentials (no OAuth redirect). Validated against firecrawl (Jun 2026):
        create a `use_custom_auth` config, then create a connected account with
        the field values — it activates immediately (status ACTIVE)."""
        info = await self.get_app(app)
        scheme = (info.auth_mode if info else "") or "API_KEY"
        cfg = await self._request(
            "POST",
            "/auth_configs",
            json={
                "toolkit": {"slug": app},
                "auth_config": {"type": "use_custom_auth", "authScheme": scheme},
            },
        )
        auth_config_id = (cfg.get("auth_config") or {}).get("id")
        if not auth_config_id:
            raise ConnectorProviderError(f"composio: no auth_config id for {app}")
        acct = await self._request(
            "POST",
            "/connected_accounts",
            json={
                "auth_config": {"id": auth_config_id},
                "connection": {"user_id": USER_ID, "data": credentials},
            },
        )
        return AuthInitiation(
            redirect_url="",
            connected_account_id=acct.get("id", ""),
            auth_config_id=auth_config_id,
            status=acct.get("status", ""),
        )

    async def get_account_status(self, account_id: str) -> str:
        data = await self._request("GET", f"/connected_accounts/{account_id}")
        return data.get("status", "UNKNOWN")

    async def get_account_info(self, account_id: str) -> dict[str, Any]:
        """Sanitized connected-account metadata for UI display.

        The raw Composio response carries token blobs in params/state/data —
        only a safe whitelist of fields ever leaves this method.
        """
        data = await self._request("GET", f"/connected_accounts/{account_id}")
        auth = data.get("auth_config") or {}
        return {
            "status": data.get("status", "UNKNOWN"),
            "auth_scheme": auth.get("auth_scheme"),
            "created_at": data.get("created_at"),
            "status_reason": data.get("status_reason"),
        }

    async def delete_account(self, account_id: str) -> bool:
        try:
            await self._request("DELETE", f"/connected_accounts/{account_id}")
            return True
        except ConnectorProviderError as e:
            log.warning("composio: delete account failed account=%s error=%s", account_id, e)
            return False

    # -- triggers --------------------------------------------------------

    async def list_trigger_types(self, app: str) -> list[dict[str, Any]]:
        """Trigger catalog for one toolkit (slug, name, description, config schema)."""
        data = await self._request(
            "GET", "/triggers_types", params={"toolkit_slugs": app}
        )
        return data.get("items", [])

    async def create_trigger_instance(
        self,
        trigger_slug: str,
        connected_account_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Upsert a live trigger instance; returns the provider instance id."""
        data = await self._request(
            "POST",
            f"/trigger_instances/{trigger_slug.upper()}/upsert",
            json={
                "connected_account_id": connected_account_id,
                "trigger_config": config or {},
            },
        )
        trigger_id = data.get("trigger_id", "")
        if not trigger_id:
            raise ConnectorProviderError(
                f"composio: no trigger_id for {trigger_slug}"
            )
        return trigger_id

    async def delete_trigger_instance(self, instance_id: str) -> bool:
        try:
            await self._request(
                "DELETE", f"/trigger_instances/manage/{instance_id}"
            )
            return True
        except ConnectorProviderError as e:
            log.warning(
                "composio: delete trigger failed instance=%s error=%s", instance_id, e
            )
            return False

    # -- execution -------------------------------------------------------

    async def execute(
        self,
        tool_slug: str,
        arguments: dict[str, Any],
        connected_account_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"user_id": USER_ID, "arguments": arguments}
        if connected_account_id:
            body["connected_account_id"] = connected_account_id
        data = await self._request("POST", f"/tools/execute/{tool_slug}", json=body)
        if not data.get("successful", False):
            raise ConnectorProviderError(
                f"{tool_slug} failed: {data.get('error') or 'unknown error'}"
            )
        return data.get("data") or {}

    async def close(self) -> None:
        await self._http.aclose()
