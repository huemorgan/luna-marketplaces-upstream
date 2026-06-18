"""hello-world-2 — a developer-authored plugin, published via zip UPLOAD.

Same shape as hello-world but it is NOT in the repo's marketplace-src/. It
demonstrates the runtime path: a developer packages this folder and uploads the
zip to their marketplace through the service — no repo commit, no redeploy.
"""

from __future__ import annotations

from luna_sdk import LunaPlugin, PluginContext, PluginManifest, ToolDef


class HelloWorld2Plugin(LunaPlugin):
    manifest = PluginManifest(
        name="hello-world-2",
        version="0.1.0",
        description="A second marketplace plugin, uploaded through the service.",
    )

    async def on_load(self, ctx: PluginContext) -> None:
        async def _hello_world_2(name: str = "world") -> dict:
            return {"greeting": f"Hello again, {name}! — uploaded to the marketplace 🚀"}

        ctx.tool_registry.register(
            self.manifest.name,
            ToolDef(
                name="hello_world_2",
                description="Return a second friendly greeting. Proof the upload path works.",
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
