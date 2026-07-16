"""Signed HTTP client for luna-tg-gateway."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .hmac import sign

log = logging.getLogger("plugin-telegram.client")

ENV_GATEWAY_URL = "LUNA_TELEGRAM_GATEWAY_URL"
ENV_SHARED_SECRET = "LUNA_TELEGRAM_SHARED_SECRET"
ENV_ACCOUNT_ID = "LUNA_TELEGRAM_ACCOUNT_ID"
ENV_ALLOWED_CHAT_IDS = "LUNA_TELEGRAM_ALLOWED_CHAT_IDS"
ENV_CP_URL = "LUNA_GATEWAY_URL"
ENV_CP_TOKEN = "LUNA_GATEWAY_TOKEN"

CONFIG_GATEWAY_URL = "plugin_telegram.gateway_url"
CONFIG_SHARED_SECRET = "plugin_telegram.shared_secret"
CONFIG_ACCOUNT_ID = "plugin_telegram.account_id"
CONFIG_ALLOWED_CHAT_IDS = "plugin_telegram.allowed_chat_ids"

VAULT_SECRET_KEY = CONFIG_SHARED_SECRET
VAULT_ACCOUNT_ID_KEY = CONFIG_ACCOUNT_ID
VAULT_GATEWAY_URL_KEY = CONFIG_GATEWAY_URL


class ControlPlaneError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


async def gateway_url(ctx) -> str:
    value = await _vault_get(ctx, VAULT_GATEWAY_URL_KEY)
    value = value or _setting(ctx, CONFIG_GATEWAY_URL, ENV_GATEWAY_URL)
    if not value:
        raise RuntimeError(f"{CONFIG_GATEWAY_URL} is not configured")
    return value.rstrip("/")


async def shared_secret(ctx) -> str:
    value = await _vault_get(ctx, VAULT_SECRET_KEY)
    value = value or _setting(ctx, CONFIG_SHARED_SECRET, ENV_SHARED_SECRET)
    if not value:
        raise RuntimeError(f"{CONFIG_SHARED_SECRET} is not configured")
    return value


async def account_id(ctx) -> str:
    return (
        await _vault_get(ctx, VAULT_ACCOUNT_ID_KEY)
        or _setting(ctx, CONFIG_ACCOUNT_ID, ENV_ACCOUNT_ID)
    )


async def inbound_secret(ctx, requested_account: str) -> str | None:
    """Resolve the secret only when the inbound account belongs to this tenant."""
    configured_account = await account_id(ctx)
    if configured_account:
        if requested_account != configured_account:
            return None
    elif requested_account != "default":
        return None
    return await shared_secret(ctx)


def control_plane(ctx) -> tuple[str, str] | None:
    base = _setting(ctx, ENV_CP_URL, ENV_CP_URL)
    token = _setting(ctx, ENV_CP_TOKEN, ENV_CP_TOKEN)
    if base and token:
        return base.rstrip("/"), token
    return None


async def cp_connect(ctx, bot_token: str) -> dict[str, Any]:
    return await _cp_request(
        ctx,
        "POST",
        "/api/agent/telegram/connect",
        json_body={"bot_token": bot_token},
        timeout=30,
    )


async def cp_status(ctx) -> dict[str, Any]:
    return await _cp_request(ctx, "GET", "/api/agent/telegram/status", timeout=15)


async def cp_disconnect(ctx) -> dict[str, Any]:
    return await _cp_request(
        ctx, "DELETE", "/api/agent/telegram/connect", timeout=30
    )


def allowed_chat_ids(ctx) -> list[str]:
    value = _setting(ctx, CONFIG_ALLOWED_CHAT_IDS, ENV_ALLOWED_CHAT_IDS)
    return [item.strip() for item in value.split(",") if item.strip()]


async def send_message(
    ctx,
    chat_id: str,
    text: str,
    reply_to: int | None = None,
) -> dict[str, Any]:
    return await _signed_post(
        ctx,
        "/send",
        {"chat_id": str(chat_id), "text": text, "reply_to": reply_to},
        timeout=30,
    )


async def send_media(
    ctx,
    chat_id: str,
    media_type: str,
    source: str,
    *,
    caption: str | None = None,
    reply_to: int | None = None,
) -> dict[str, Any]:
    return await _signed_post(
        ctx,
        "/send-media",
        {
            "chat_id": str(chat_id),
            "kind": media_type,
            "media": source,
            "caption": caption,
            "reply_to": reply_to,
        },
        timeout=60,
    )


async def react_message(
    ctx,
    chat_id: str,
    tg_msg_id: int,
    emoji: str,
) -> dict[str, Any]:
    return await _signed_post(
        ctx,
        "/react",
        {"chat_id": str(chat_id), "message_id": int(tg_msg_id), "emoji": emoji},
        timeout=20,
    )


async def send_typing(ctx, chat_id: str, action: str = "typing") -> dict[str, Any]:
    return await _signed_post(
        ctx,
        "/typing",
        {"chat_id": str(chat_id), "action": action},
        timeout=10,
    )


async def health(ctx) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as session:
        response = await session.get(f"{await gateway_url(ctx)}/health")
        response.raise_for_status()
        return response.json()


async def _signed_post(
    ctx,
    path: str,
    payload: dict[str, Any],
    *,
    timeout: int,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = await signed_headers(ctx, body)
    async with httpx.AsyncClient(timeout=timeout) as session:
        response = await session.post(
            f"{await gateway_url(ctx)}{path}",
            content=body.encode("utf-8"),
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


async def signed_headers(ctx, body: str) -> dict[str, str]:
    timestamp, signature = sign(await shared_secret(ctx), body)
    headers = {
        "content-type": "application/json",
        "x-tg-timestamp": timestamp,
        "x-tg-signature": signature,
    }
    configured_account = await account_id(ctx)
    if configured_account:
        headers["x-tg-account"] = configured_account
    return headers


def outbound_message_id(response: dict[str, Any]) -> int | None:
    """Read message ID from canonical or compatibility gateway responses."""
    value = response.get("tg_msg_id")
    if value is None:
        result = response.get("result")
        if isinstance(result, dict):
            value = result.get("message_id")
    if value is None:
        value = response.get("message_id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _setting(ctx, config_key: str, env_key: str) -> str:
    getter = getattr(ctx, "get_env", None)
    if getter is not None:
        for key in (config_key, env_key):
            value = getter(key)
            if value:
                return str(value).strip()
    config = getattr(ctx, "config", None)
    if isinstance(config, dict):
        value = config.get(config_key)
        if value:
            return str(value).strip()
    return (os.environ.get(env_key) or "").strip()


async def _vault_get(ctx, key: str) -> str:
    vault = getattr(ctx, "vault", None)
    if vault is None:
        return ""
    try:
        credential = await vault.get_credential(key)
    except KeyError:
        return ""
    except Exception as exc:  # noqa: BLE001
        log.warning("vault read failed for %s: %s", key, exc)
        return ""
    return str(getattr(credential, "value", "") or "").strip()


async def _cp_request(
    ctx,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: int,
) -> dict[str, Any]:
    connection = control_plane(ctx)
    if connection is None:
        raise ControlPlaneError(
            "Hosted Telegram provisioning is unavailable on this Luna.",
            status_code=400,
        )
    base, token = connection
    headers = {"authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as session:
            response = await session.request(
                method, f"{base}{path}", headers=headers, json=json_body
            )
    except httpx.HTTPError as exc:
        raise ControlPlaneError("Telegram hosting service is unreachable.") from exc
    if response.status_code in {400, 401, 403, 422}:
        raise ControlPlaneError(
            "BotFather token was rejected. Check the token and try again.",
            status_code=400,
        )
    if response.status_code >= 400:
        raise ControlPlaneError(
            "Telegram hosting service could not complete the request.",
            status_code=502,
        )
    if not response.content:
        return {"ok": True}
    try:
        value = response.json()
    except ValueError as exc:
        raise ControlPlaneError(
            "Telegram hosting service returned an invalid response."
        ) from exc
    if not isinstance(value, dict):
        raise ControlPlaneError("Telegram hosting service returned an invalid response.")
    return value
