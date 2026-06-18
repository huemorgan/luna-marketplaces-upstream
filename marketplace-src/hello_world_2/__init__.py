"""hello-world-2 — the second core plugin in the official marketplace.

Same shape as hello-world. It exists to prove the catalog grows: adding a
package under marketplace-src/ seeds it into the official marketplace on boot,
and it shows up in Luna's Marketplace pane next to hello-world.
"""

from __future__ import annotations

from luna_sdk import LunaPlugin, PluginContext, PluginManifest, ToolDef


class HelloWorld2Plugin(LunaPlugin):
    manifest = PluginManifest(
        name="hello-world-2",
        version="0.1.0",
        description="A second marketplace plugin. Says hello again.",
    )

    async def on_load(self, ctx: PluginContext) -> None:
        async def _hello_world_2(name: str = "world") -> dict:
            return {"greeting": f"Hello again, {name}! — from the marketplace 🚀"}

        ctx.tool_registry.register(
            self.manifest.name,
            ToolDef(
                name="hello_world_2",
                description="Return a second friendly greeting.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Who to greet (default: world)"}
                    },
                    "required": [],
                },
                policy="auto_approve",
                risk_level="low",
            ),
            _hello_world_2,
        )
