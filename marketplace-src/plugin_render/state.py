"""Process-level holder for the live RenderClient.

008.5/phase05: decoupled from `get_plugin_registry()`. The routes used to
reach into the registered plugin instance to swap its `_client` on
connect/disconnect. Instead, the client lives here as a module singleton that
both `on_load` and the routes share via relative import — no core loader
coupling, works the same from a managed dir.
"""

from __future__ import annotations

from .client import RenderClient

_client: RenderClient | None = None


def get_client() -> RenderClient | None:
    return _client


def set_client(client: RenderClient | None) -> None:
    global _client
    _client = client
