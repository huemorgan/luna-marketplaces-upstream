"""Web search backends for plugin-web-access (005.902).

Two providers behind one interface: Tavily (default, agent-tuned) and Google
Custom Search. Provider + keys come from env for this slice
(`LUNA_WEB_SEARCH_PROVIDER`, `LUNA_TAVILY_API_KEY`, `LUNA_GOOGLE_SEARCH_API_KEY`,
`LUNA_GOOGLE_SEARCH_CX`); a Settings-UI/vault-backed selector is the deferred
slice (see NOTES.md). Core functions take an `httpx.AsyncClient` so tests can
inject an `httpx.MockTransport` — no real network, no extra deps.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

TAVILY_DEFAULT_ENDPOINT = "https://api.tavily.com/search"
GOOGLE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
DEFAULT_TIMEOUT = 20.0


async def _resolve_credential(
    name: str, env_var: str | None, vault: Any | None
) -> str | None:
    """Vault first, env var fallback. SDK-only: uses the `vault` object handed in
    via `ctx.vault` (its `get_credential(name)` returns an object with `.value`),
    then falls back to the env var. No `import luna.*` — that's the whole point
    of running from the marketplace.
    """
    if vault is not None:
        try:
            cred = await vault.get_credential(name)
            return cred.value
        except KeyError:
            pass
        except PermissionError:
            # ACL denied this requester — fall through to env so a host-provided
            # key still works; never silently expose a value we can't read.
            pass
    if env_var:
        val = os.environ.get(env_var, "").strip()
        if val:
            return val
    return None


def tavily_endpoint() -> str:
    """007.001: `LUNA_TAVILY_BASE_URL` routes Tavily traffic through a
    gateway/proxy. Accepts a bare origin or a full /search URL."""
    base = (os.environ.get("LUNA_TAVILY_BASE_URL") or "").strip()
    if not base:
        return TAVILY_DEFAULT_ENDPOINT
    base = base.rstrip("/")
    return base if base.endswith("/search") else f"{base}/search"


# Back-compat alias for existing imports/tests.
TAVILY_ENDPOINT = TAVILY_DEFAULT_ENDPOINT


def _clamp(n: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(int(n or default), hi))
    except (TypeError, ValueError):
        return default


async def tavily_search(
    client: httpx.AsyncClient, api_key: str, query: str, max_results: int
) -> dict[str, Any]:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": True,
        "search_depth": "basic",
    }
    resp = await client.post(tavily_endpoint(), json=payload)
    resp.raise_for_status()
    data = resp.json()
    results = [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": (r.get("content") or "")[:1000]}
        for r in (data.get("results") or [])
    ]
    return {"answer": data.get("answer") or "", "results": results}


async def google_search(
    client: httpx.AsyncClient, api_key: str, cx: str, query: str, max_results: int
) -> dict[str, Any]:
    params = {"key": api_key, "cx": cx, "q": query, "num": max_results}
    resp = await client.get(GOOGLE_ENDPOINT, params=params)
    resp.raise_for_status()
    data = resp.json()
    results = [
        {"title": it.get("title", ""), "url": it.get("link", ""), "content": (it.get("snippet") or "")[:1000]}
        for it in (data.get("items") or [])
    ]
    return {"answer": "", "results": results}


async def run_search(
    query: str,
    max_results: int = 5,
    *,
    client: httpx.AsyncClient | None = None,
    vault: Any | None = None,
) -> dict[str, Any]:
    """Dispatch a search to the configured provider. Never raises — returns an
    error dict the agent can read and relay (missing key, HTTP error, etc.).

    005.906: vault-first credential resolution. Keys are looked up in the vault
    first, falling back to env vars for deployment/infra scenarios.
    """
    resolve_credential = _resolve_credential

    query = (query or "").strip()
    if not query:
        return {"error": "empty query", "detail": "Provide a non-empty search query."}
    n = _clamp(max_results, 1, 10, 5)
    provider = (os.environ.get("LUNA_WEB_SEARCH_PROVIDER") or "tavily").strip().lower()

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        if provider == "google":
            key = await resolve_credential("google_search_api_key", "LUNA_GOOGLE_SEARCH_API_KEY", vault)
            cx = await resolve_credential("google_search_cx", "LUNA_GOOGLE_SEARCH_CX", vault)
            if not key or not cx:
                return {
                    "error": "web_search (google) is not configured",
                    "detail": "Store google_search_api_key and google_search_cx in "
                    "Settings → Credentials, or set LUNA_GOOGLE_SEARCH_API_KEY and "
                    "LUNA_GOOGLE_SEARCH_CX env vars.",
                }
            out = await google_search(client, key, cx, query, n)
        else:
            key = await resolve_credential("tavily_api_key", "LUNA_TAVILY_API_KEY", vault)
            if not key:
                return {
                    "error": "web_search is not configured",
                    "detail": "Store tavily_api_key in Settings → Credentials "
                    "(get a key at https://tavily.com), or set LUNA_TAVILY_API_KEY env var.",
                }
            out = await tavily_search(client, key, query, n)
            provider = "tavily"
    except httpx.HTTPStatusError as exc:
        return {"error": "search request failed", "detail": f"HTTP {exc.response.status_code}", "query": query, "provider": provider}
    except httpx.HTTPError as exc:
        return {"error": "search request failed", "detail": str(exc), "query": query, "provider": provider}
    finally:
        if owns_client:
            await client.aclose()

    return {
        "query": query,
        "provider": provider,
        "answer": out["answer"],
        "results": out["results"],
        "result_count": len(out["results"]),
    }
