"""Async HTTP client wrapper for the FunnelFighters API."""

from __future__ import annotations

import httpx


class FFClient:
    def __init__(self, base_url: str, api_key: str, org_id: str):
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "x-organization-id": org_id,
            },
            timeout=30.0,
        )

    async def get(self, path: str, params: dict | None = None) -> dict:
        resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, json: dict | None = None) -> dict:
        resp = await self._http.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._http.aclose()
