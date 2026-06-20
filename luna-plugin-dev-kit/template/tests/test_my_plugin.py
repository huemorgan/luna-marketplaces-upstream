"""Unit tests for the plugin's tool logic — the inner loop, no Luna runtime needed.

Run: `pip install -e . && pytest`
"""

import asyncio

from my_plugin import MyPlugin


class _FakeToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, plugin_name, tool_def, handler, **kwargs):
        self.tools[tool_def.name] = handler


class _FakeContext:
    def __init__(self):
        self.tool_registry = _FakeToolRegistry()
        self.vault = None
        self.skill_registry = None


def _load_plugin():
    plugin = MyPlugin()
    ctx = _FakeContext()
    asyncio.run(plugin.on_load(ctx))
    return ctx


def test_manifest_identity():
    assert MyPlugin.manifest.name == "my-plugin"
    assert MyPlugin.manifest.version == "0.1.0"


def test_registers_hello_tool():
    ctx = _load_plugin()
    assert "hello" in ctx.tool_registry.tools


def test_hello_returns_greeting():
    ctx = _load_plugin()
    result = asyncio.run(ctx.tool_registry.tools["hello"](name="Luna"))
    assert "Luna" in result["greeting"]
