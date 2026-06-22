"""Module-level handle to the live ConnectorsPlugin (008.5/phase13).

Decoupling: routes used to find the plugin by walking the core plugin registry
(`luna.plugins.loader.get_plugin_registry`). A managed-dir plugin can't import
that. Instead the plugin registers itself here in ``on_load`` and the routes read
it — same pattern as the other extracted plugins' ``state.py`` singletons.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import ConnectorsPlugin

_plugin: ConnectorsPlugin | None = None


def set_plugin(plugin: ConnectorsPlugin | None) -> None:
    global _plugin
    _plugin = plugin


def get_plugin() -> ConnectorsPlugin | None:
    return _plugin
