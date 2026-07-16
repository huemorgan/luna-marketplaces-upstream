"""Hosted Telegram account provisioning through the tenant control plane."""

from __future__ import annotations

import logging
from typing import Any

from . import client

log = logging.getLogger("plugin-telegram.provision")

_CREDENTIAL_KEYS = (
    client.VAULT_GATEWAY_URL_KEY,
    client.VAULT_ACCOUNT_ID_KEY,
    client.VAULT_SECRET_KEY,
)


class ProvisionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def mode(ctx) -> str:
    return "hosted" if client.control_plane(ctx) is not None else "manual"


async def connect_bot(ctx, bot_token: str, *, connect=None) -> dict[str, Any]:
    """Exchange one request-local BotFather token for tenant credentials."""
    if mode(ctx) != "hosted":
        raise ProvisionError(
            "Self-hosted Luna uses manual Telegram gateway configuration.",
            status_code=400,
        )
    token = str(bot_token or "").strip()
    if not token:
        raise ProvisionError("BotFather token is required.", status_code=400)
    if len(token) > 512:
        raise ProvisionError("BotFather token is invalid.", status_code=400)
    vault = getattr(ctx, "vault", None)
    if vault is None:
        raise ProvisionError("Luna vault is unavailable.", status_code=503)

    call = connect or client.cp_connect
    try:
        response = await call(ctx, token)
    except client.ControlPlaneError as exc:
        raise ProvisionError(str(exc), status_code=exc.status_code) from None
    except Exception:
        log.warning("tg.connect_failed")
        raise ProvisionError("Telegram hosting service could not connect the bot.") from None

    gateway_url = _required(response, "gateway_url")
    account_id = _required(response, "account_id")
    previous = {key: await client._vault_get(ctx, key) for key in _CREDENTIAL_KEYS}
    returned_secret = str(response.get("shared_secret") or "").strip()
    same_account = previous[client.VAULT_ACCOUNT_ID_KEY] == account_id
    same_gateway = (
        previous[client.VAULT_GATEWAY_URL_KEY].rstrip("/")
        == gateway_url.rstrip("/")
    )
    existing_secret = previous[client.VAULT_SECRET_KEY]
    if not returned_secret and not (
        existing_secret and same_account and same_gateway
    ):
        raise ProvisionError(
            "Telegram hosting service returned no shared secret for this account. "
            "Retry with the same BotFather token.",
            status_code=502,
        )
    values = {
        client.VAULT_GATEWAY_URL_KEY: gateway_url,
        client.VAULT_ACCOUNT_ID_KEY: account_id,
    }
    if returned_secret:
        values[client.VAULT_SECRET_KEY] = returned_secret
    try:
        for key, value in values.items():
            await vault.store_credential(key, value)
    except Exception:
        await _restore_vault(vault, previous)
        log.warning("tg.connect_vault_write_failed")
        raise ProvisionError("Telegram credentials could not be saved.") from None

    log.info("tg.connected")
    return {
        "ok": True,
        "mode": "hosted",
        "connected": True,
        "bot": _safe_bot(response.get("bot")),
        "status": _safe_scalar(response.get("status")),
    }


async def status(ctx, *, get_status=None) -> dict[str, Any]:
    if mode(ctx) == "manual":
        configured = bool(
            await _configured_value(ctx, client.gateway_url)
            and await _configured_value(ctx, client.shared_secret)
        )
        gateway = None
        error = None
        if configured:
            try:
                gateway = await client.health(ctx)
            except Exception:
                error = "Telegram gateway is unreachable."
        return {
            "mode": "manual",
            "configured": configured,
            "connected": bool(gateway and gateway.get("status") == "ok"),
            "gateway": _safe_gateway_health(gateway),
            "error": error,
        }

    configured_values = [
        await client._vault_get(ctx, key) for key in _CREDENTIAL_KEYS
    ]
    configured = all(configured_values)
    call = get_status or client.cp_status
    try:
        response = await call(ctx)
    except client.ControlPlaneError as exc:
        return {
            "mode": "hosted",
            "configured": configured,
            "connected": False,
            "bot": None,
            "status": None,
            "error": str(exc),
        }
    except Exception:
        log.warning("tg.status_failed")
        return {
            "mode": "hosted",
            "configured": configured,
            "connected": False,
            "bot": None,
            "status": None,
            "error": "Telegram hosting service is unreachable.",
        }
    status_value = _safe_scalar(response.get("status"))
    active_status = (
        isinstance(status_value, str)
        and status_value.casefold() in {"active", "connected", "ready", "ok"}
    )
    connected = bool(
        response.get("connected")
        or (
            response.get("exists") is not False
            and response.get("enabled") is not False
            and active_status
        )
    )
    return {
        "mode": "hosted",
        "configured": configured,
        "connected": connected,
        "bot": _safe_bot(response.get("bot")),
        "status": status_value,
        "privacy": _safe_privacy(response),
        "error": None,
    }


async def disconnect_bot(ctx, *, disconnect=None) -> dict[str, Any]:
    if mode(ctx) != "hosted":
        raise ProvisionError(
            "Self-hosted Luna uses manual Telegram gateway configuration.",
            status_code=400,
        )
    call = disconnect or client.cp_disconnect
    try:
        await call(ctx)
    except client.ControlPlaneError as exc:
        raise ProvisionError(str(exc), status_code=exc.status_code) from None
    except Exception:
        log.warning("tg.disconnect_failed")
        raise ProvisionError("Telegram hosting service could not disconnect the bot.") from None

    vault = getattr(ctx, "vault", None)
    if vault is not None:
        for key in _CREDENTIAL_KEYS:
            try:
                await vault.delete_credential(key)
            except Exception:
                log.warning("tg.disconnect_vault_cleanup_failed key=%s", key)
    log.info("tg.disconnected")
    return {"ok": True, "mode": "hosted", "connected": False}


def _required(response: Any, key: str) -> str:
    if not isinstance(response, dict):
        raise ProvisionError("Telegram hosting service returned an invalid response.")
    value = str(response.get(key) or "").strip()
    if not value:
        raise ProvisionError("Telegram hosting service returned incomplete credentials.")
    return value


def _safe_bot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed = {
        "id", "username", "first_name", "can_join_groups",
        "can_read_all_group_messages", "supports_inline_queries",
    }
    return {key: item for key, item in value.items() if key in allowed}


def _safe_privacy(response: dict[str, Any]) -> dict[str, Any] | None:
    privacy = response.get("privacy")
    if isinstance(privacy, dict):
        allowed = {"can_read_all_group_messages", "privacy_mode"}
        return {key: value for key, value in privacy.items() if key in allowed}
    bot = response.get("bot")
    can_read = (
        bot.get("can_read_all_group_messages")
        if isinstance(bot, dict)
        else None
    )
    privacy_mode = response.get("privacy_mode")
    if isinstance(can_read, bool):
        return {
            "can_read_all_group_messages": can_read,
            "privacy_mode": privacy_mode,
        }
    if isinstance(privacy_mode, bool):
        return {
            "can_read_all_group_messages": not privacy_mode,
            "privacy_mode": privacy_mode,
        }
    return None


def _safe_gateway_health(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed = {"status", "connected", "bot", "webhook", "last_activity"}
    result = {key: item for key, item in value.items() if key in allowed}
    if "bot" in result:
        result["bot"] = _safe_bot(result["bot"])
    return result


def _safe_scalar(value: Any) -> str | bool | int | None:
    return value if isinstance(value, (str, bool, int)) else None


async def _configured_value(ctx, getter) -> str:
    try:
        return await getter(ctx)
    except RuntimeError:
        return ""


async def _restore_vault(vault, previous: dict[str, str]) -> None:
    for key, value in previous.items():
        try:
            if value:
                await vault.store_credential(key, value)
            else:
                await vault.delete_credential(key)
        except Exception:
            pass
