"""Process-level holder for the live FFClient.

008.5/phase09: decoupled from `get_plugin_registry()`. The connect/disconnect
routes used to reach into the registered plugin instance to swap its `_client`.
Instead the client lives here as a module singleton shared by `on_load` and the
routes via relative import — no core loader coupling, works the same from a
managed dir.
"""

from __future__ import annotations

from .client import FFClient

_client: FFClient | None = None


def get_client() -> FFClient | None:
    return _client


def set_client(client: FFClient | None) -> None:
    global _client
    _client = client
