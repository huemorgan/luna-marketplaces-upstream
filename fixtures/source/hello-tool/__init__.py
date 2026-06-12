"""Hello Tool — a demo plugin for the Luna marketplace protocol."""

from __future__ import annotations


async def greet(name: str = "World") -> str:
    return f"Hello, {name}! Nice to meet you."
