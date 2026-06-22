"""ConnectorProvider protocol — the thin abstraction every provider driver implements.

Luna is open source: nothing outside this plugin may import a concrete provider
(Composio, Pipedream, ...). Tool registration, the settings UI, the events
ingress, and the agent management tools all code against this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class AuthField:
    """One credential input a custom-auth toolkit needs from the user.

    Sourced from the provider's auth field spec (e.g. Composio
    `connected_account_initiation.required`). `secret` drives a password
    input in the UI; `default` pre-fills non-secret fields (e.g. a base URL).
    """

    name: str
    label: str
    type: str = "string"
    required: bool = True
    secret: bool = False
    default: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "secret": self.secret,
            "default": self.default,
            "description": self.description,
        }


@dataclass
class AppInfo:
    """One connectable app in a provider's catalog."""

    slug: str
    name: str
    description: str = ""
    logo: str | None = None
    no_auth: bool = False
    tools_count: int = 0
    triggers_count: int = 0
    categories: list[str] = field(default_factory=list)
    # 007.014: auth shape from the catalog detail. Empty when unknown (the
    # list endpoint omits it). "OAUTH2"/"OAUTH1" → managed redirect; "API_KEY"/
    # "BEARER_TOKEN"/"BASIC"/… → custom auth, collect `auth_fields` from user.
    auth_mode: str = ""
    auth_fields: list[AuthField] = field(default_factory=list)

    @property
    def needs_custom_auth(self) -> bool:
        mode = (self.auth_mode or "").upper()
        return bool(mode) and mode != "NO_AUTH" and not mode.startswith("OAUTH")


@dataclass
class AuthInitiation:
    """Result of starting a connection.

    OAuth: `redirect_url` is non-empty and the user must visit it.
    Custom auth (API key): `redirect_url` is empty and `status` reflects the
    connected account ("ACTIVE" means done immediately).
    """

    redirect_url: str
    connected_account_id: str
    auth_config_id: str
    status: str = ""


@dataclass
class ProviderToolDef:
    """Normalized tool schema from a provider catalog."""

    slug: str
    name: str
    description: str
    parameters: dict[str, Any]
    destructive: bool = False
    read_only: bool = False


class ConnectorProviderError(Exception):
    """Single error shape for all provider failures."""


@runtime_checkable
class ConnectorProvider(Protocol):
    """Driver contract. Implementations: providers/composio.py (more later)."""

    name: str

    async def validate(self) -> bool: ...

    async def list_apps(self, search: str = "", limit: int = 50) -> list[AppInfo]: ...

    async def get_app(self, slug: str) -> AppInfo | None: ...

    async def list_tools(self, app: str, limit: int = 60) -> list[ProviderToolDef]: ...

    async def initiate_connection(self, app: str) -> AuthInitiation: ...

    async def initiate_custom_connection(
        self, app: str, credentials: dict[str, str]
    ) -> AuthInitiation: ...

    async def get_account_status(self, account_id: str) -> str: ...

    async def delete_account(self, account_id: str) -> bool: ...

    async def execute(
        self,
        tool_slug: str,
        arguments: dict[str, Any],
        connected_account_id: str | None = None,
    ) -> dict[str, Any]: ...

    # -- triggers (006.713) ------------------------------------------------

    async def list_trigger_types(self, app: str) -> list[dict[str, Any]]: ...

    async def create_trigger_instance(
        self,
        trigger_slug: str,
        connected_account_id: str,
        config: dict[str, Any] | None = None,
    ) -> str: ...

    async def delete_trigger_instance(self, instance_id: str) -> bool: ...

    async def close(self) -> None: ...
