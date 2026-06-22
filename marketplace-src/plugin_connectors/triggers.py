"""ConnectorTriggerSource — publishes provider triggers through luna.triggers.

The connectors plugin doesn't know who listens (playbooks today, anything
tomorrow). Consumers find triggers via ctx.trigger_sources and subscribe to
the advertised event bus pattern; the webhook ingress emits those events.

Lifecycle: the per-app "Triggers" toggle only *exposes* triggers in
list_triggers(). Provider-side instances (API quota, webhook traffic) are
created lazily on the first ensure_trigger() from a consumer and torn down
when the last reference is released (refcounted in plugin state).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from luna_sdk import TriggerInfo

from .protocol import ConnectorProviderError

if TYPE_CHECKING:
    from . import ConnectorsPlugin

log = logging.getLogger("plugin-connectors.triggers")


def normalized_event(app_slug: str, trigger_slug: str) -> str:
    """Canonical bus event for a provider trigger — MUST stay in sync with
    the webhook ingress normalization in ConnectorsPlugin.handle_provider_event."""
    app = app_slug.lower()
    trig = trigger_slug.lower()
    if trig.startswith(f"{app}_"):
        trig = trig[len(app) + 1 :]
    return f"connector.{app}.{trig}"


class ConnectorTriggerSource:
    source_name = "connectors"

    def __init__(self, plugin: ConnectorsPlugin) -> None:
        self._plugin = plugin

    # -- discovery ---------------------------------------------------------

    async def list_triggers(self, app: str | None = None) -> list[TriggerInfo]:
        """Triggers of connected apps whose Triggers toggle is on."""
        out: list[TriggerInfo] = []
        for slug, state in self._plugin.apps_with_triggers_enabled():
            if app is not None and slug != app:
                continue
            provider = self._plugin.provider_for(slug)
            if provider is None:
                continue
            try:
                items = await provider.list_trigger_types(slug)
            except ConnectorProviderError as e:
                log.warning("connectors: trigger list failed app=%s error=%s", slug, e)
                continue
            for item in items:
                t_slug = str(item.get("slug", "")).lower()
                if not t_slug:
                    continue
                out.append(
                    TriggerInfo(
                        slug=t_slug,
                        source=self.source_name,
                        app=slug,
                        label=item.get("name", t_slug),
                        event_pattern=normalized_event(slug, t_slug),
                        config_schema=item.get("config") or {},
                        payload_example=item.get("payload"),
                        description=(item.get("description") or "")[:300],
                    )
                )
        return out

    # -- lifecycle (refcounted) ---------------------------------------------

    async def ensure_trigger(self, slug: str, config: dict[str, Any]) -> str:
        """Create the provider instance on first reference, reuse afterwards."""
        key = slug.lower()
        instances = self._plugin.trigger_instances()
        entry = instances.get(key)
        if entry is not None:
            entry["refs"] = int(entry.get("refs", 0)) + 1
            await self._plugin.save_state()
            return str(entry["id"])

        app_slug, app = self._plugin.app_for_trigger(key)
        if app is None:
            raise ConnectorProviderError(f"No connected app exposes trigger '{slug}'")
        if not app.get("enabled_triggers"):
            raise ConnectorProviderError(
                f"Triggers are not enabled for '{app_slug}' — flip the Triggers "
                "toggle in Settings → Connectors first."
            )
        provider = self._plugin.provider_for(app_slug)
        account_id = app.get("connected_account_id")
        if provider is None or not account_id:
            raise ConnectorProviderError(
                f"'{app_slug}' has no connected account for triggers"
            )

        instance_id = await provider.create_trigger_instance(key, account_id, config)
        instances[key] = {"id": instance_id, "refs": 1, "app": app_slug}
        await self._plugin.save_state()
        log.info("connectors: trigger ensured trigger=%s instance=%s", key, instance_id)
        return instance_id

    async def release_trigger(self, slug: str) -> None:
        key = slug.lower()
        instances = self._plugin.trigger_instances()
        entry = instances.get(key)
        if entry is None:
            return
        entry["refs"] = int(entry.get("refs", 1)) - 1
        if entry["refs"] > 0:
            await self._plugin.save_state()
            return
        instances.pop(key, None)
        await self._plugin.save_state()
        provider = self._plugin.provider_for(entry.get("app", ""))
        if provider is not None:
            await provider.delete_trigger_instance(str(entry["id"]))
        log.info("connectors: trigger released trigger=%s instance=%s", key, entry["id"])
