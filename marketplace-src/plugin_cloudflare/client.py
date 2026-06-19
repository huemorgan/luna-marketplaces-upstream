"""Async HTTP client wrapper for the Cloudflare API (v4)."""

from __future__ import annotations

from typing import Any

import httpx


class CloudflareClient:
    BASE_URL = "https://api.cloudflare.com/client/v4/"

    def __init__(self, api_token: str, account_id: str) -> None:
        self._account_id = account_id
        self._http = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=30.0,
        )

    @property
    def account_id(self) -> str:
        return self._account_id

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type

        resp = await self._http.request(
            method,
            path,
            json=json,
            params=params,
            content=content,
            headers=headers if headers else None,
        )
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return {"text": resp.text}

    # --- Zones / DNS ---

    async def list_zones(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", "zones", params=params)

    async def list_dns_records(
        self, zone_id: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", f"zones/{zone_id}/dns_records", params=params)

    async def create_dns_record(self, zone_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"zones/{zone_id}/dns_records", json=data)

    async def update_dns_record(
        self, zone_id: str, record_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request(
            "PATCH", f"zones/{zone_id}/dns_records/{record_id}", json=data
        )

    async def delete_dns_record(self, zone_id: str, record_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"zones/{zone_id}/dns_records/{record_id}")

    # --- Cache ---

    async def purge_cache(self, zone_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"zones/{zone_id}/purge_cache", json=data)

    # --- Workers ---

    async def list_workers(self) -> dict[str, Any]:
        return await self._request(
            "GET", f"accounts/{self._account_id}/workers/scripts"
        )

    async def get_worker(self, name: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"accounts/{self._account_id}/workers/scripts/{name}"
        )

    async def deploy_worker(self, name: str, script: str) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"accounts/{self._account_id}/workers/scripts/{name}",
            content=script.encode("utf-8"),
            content_type="application/javascript",
        )

    # --- KV ---

    async def list_kv_namespaces(
        self, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"accounts/{self._account_id}/storage/kv/namespaces", params=params
        )

    async def kv_get(self, namespace_id: str, key: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"accounts/{self._account_id}/storage/kv/namespaces/{namespace_id}/values/{key}",
        )

    async def kv_put(self, namespace_id: str, key: str, value: str) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"accounts/{self._account_id}/storage/kv/namespaces/{namespace_id}/values/{key}",
            content=value.encode("utf-8"),
            content_type="text/plain",
        )

    async def kv_delete(self, namespace_id: str, key: str) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            f"accounts/{self._account_id}/storage/kv/namespaces/{namespace_id}/values/{key}",
        )

    # --- Pages ---

    async def list_pages_projects(
        self, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"accounts/{self._account_id}/pages/projects", params=params
        )

    async def get_pages_project(self, name: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"accounts/{self._account_id}/pages/projects/{name}"
        )

    # --- Lifecycle ---

    async def close(self) -> None:
        await self._http.aclose()
