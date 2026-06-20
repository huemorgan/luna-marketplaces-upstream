"""my-plugin — a starter Luna plugin.

Authored against `luna_sdk` ONLY (never `import luna.*`). Rename the package dir
(`my_plugin/`) and update every "my-plugin" / "my_plugin" identifier to your own.
See ../docs/CREATING-A-PLUGIN.md.
"""

from __future__ import annotations

from luna_sdk import LunaPlugin, PluginContext, PluginManifest, ToolDef


class MyPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="my-plugin",  # kebab-case; must match luna-plugin.toml
        version="0.1.0",  # bump (here AND in the toml) for every published change
        description="A starter Luna plugin. Replace me.",
    )

    async def on_load(self, ctx: PluginContext) -> None:
        async def _hello(name: str = "world") -> dict:
            return {"greeting": f"Hello, {name}! — from my-plugin"}

        ctx.tool_registry.register(
            self.manifest.name,
            ToolDef(
                name="hello",
                description="Return a friendly greeting. Replace with your real tool.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Who to greet (default: world)"},
                    },
                    "required": [],
                },
                policy="auto_approve",  # auto_approve | ask | prompt_always
                risk_level="low",  # low | medium | high
            ),
            _hello,
        )
