"""hello-world — the first plugin published to our marketplace.

Authored against `luna_sdk` ONLY (no `import luna.*`). The marketplace packages
+ hashes it; a Luna agent fetches it back, verifies the hash, and loads it.
One tool, no DB, no routes, no UI, no deps.
"""

from __future__ import annotations

from luna_sdk import LunaPlugin, PluginContext, PluginManifest, ToolDef


class HelloWorldPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="hello-world",
        version="0.1.0",
        description="The first marketplace-installed Luna plugin. Says hello.",
    )

    async def on_load(self, ctx: PluginContext) -> None:
        async def _hello_world(name: str = "world") -> dict:
            return {"greeting": f"Hello, {name}! — from the marketplace 🌙"}

        ctx.tool_registry.register(
            self.manifest.name,
            ToolDef(
                name="hello_world",
                description="Return a friendly greeting. Proof a marketplace plugin works.",
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
            _hello_world,
        )
