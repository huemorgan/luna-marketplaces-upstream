"""FunnelFighters agent-facing tools — 15 read-only endpoints."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from luna_sdk import ToolDef

from .client import FFClient

MAX_RESPONSE_CHARS = 4000

# Returned when the plugin is enabled but no credentials are configured yet.
# The agent surfaces this to the user instead of crashing the turn.
_NOT_CONNECTED = {
    "error": "not_connected",
    "detail": "FunnelFighters is not connected. Add the API key and org ID in Settings > FunnelFighters.",
}

ClientProvider = Callable[[], FFClient]


def _truncate(data: Any) -> str:
    """Serialize response and truncate if over MAX_RESPONSE_CHARS."""
    text = json.dumps(data, default=str)
    if len(text) > MAX_RESPONSE_CHARS:
        return text[:MAX_RESPONSE_CHARS] + "...truncated"
    return text


def _date_params(start_date: str | None, end_date: str | None) -> dict | None:
    params: dict[str, str] = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return params or None


async def _safe_get(get_client: ClientProvider, path: str, params: dict | None = None) -> dict:
    try:
        client = get_client()
    except RuntimeError:
        return dict(_NOT_CONNECTED)
    try:
        data = await client.get(path, params=params)
        return {"result": _truncate(data)}
    except httpx.HTTPStatusError as e:
        return {"error": e.response.status_code, "detail": e.response.text[:500]}


async def _safe_post(get_client: ClientProvider, path: str, json_body: dict | None = None) -> dict:
    try:
        client = get_client()
    except RuntimeError:
        return dict(_NOT_CONNECTED)
    try:
        data = await client.post(path, json=json_body)
        return {"result": _truncate(data)}
    except httpx.HTTPStatusError as e:
        return {"error": e.response.status_code, "detail": e.response.text[:500]}


def build_tools(get_client: ClientProvider) -> list[tuple[ToolDef, Any]]:
    """Return (ToolDef, handler) pairs for all FF tools.

    `get_client` is called lazily per invocation so tools stay registered even
    before the user connects credentials. It raises ``RuntimeError`` until a
    client is configured; the safe wrappers translate that into a friendly
    "not connected" result.
    """

    async def ff_portfolio_summary(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Get portfolio summary — spend, visitors, signups, activated, paying, revenue, tROI."""
        return await _safe_get(get_client, "/api/portfolio/summary", _date_params(start_date, end_date))

    async def ff_campaigns(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """List all campaigns with metrics for a date range."""
        return await _safe_get(get_client, "/api/campaigns/", _date_params(start_date, end_date))

    async def ff_campaign_detail(
        campaign_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Deep dive into a campaign — hourly metrics, impression share, audience/device/geo breakdown."""
        return await _safe_get(get_client, f"/api/campaigns/{campaign_id}", _date_params(start_date, end_date))

    async def ff_ads(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """List ads with performance metrics."""
        return await _safe_get(get_client, "/api/ads/", _date_params(start_date, end_date))

    async def ff_ad_detail(
        ad_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Ad creative, funnel through-rate, versions, agent action history."""
        return await _safe_get(get_client, f"/api/ads/{ad_id}", _date_params(start_date, end_date))

    async def ff_funnel(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Full waterfall: impressions → clicks → visitors → signups → activated → paying."""
        return await _safe_get(get_client, "/api/funnel/", _date_params(start_date, end_date))

    async def ff_cohorts(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Weekly signup cohorts with conversion progression."""
        return await _safe_get(get_client, "/api/cohorts/weekly", _date_params(start_date, end_date))

    async def ff_keywords(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Keyword performance + search terms."""
        return await _safe_get(get_client, "/api/keywords/", _date_params(start_date, end_date))

    async def ff_wasted_spend(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Wasted spend analysis — identify budget going to non-converting paths."""
        return await _safe_get(get_client, "/api/insights/wasted-spend", _date_params(start_date, end_date))

    async def ff_landing_pages(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Landing page performance — signup rates, bounce rates."""
        return await _safe_get(get_client, "/api/landing-pages/", _date_params(start_date, end_date))

    async def ff_duck_reports(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Get 4 Ducks alignment reports."""
        return await _safe_get(get_client, "/api/duck-reports/", _date_params(start_date, end_date))

    async def ff_duck_analyze(
        campaign_id: str | None = None,
    ) -> dict:
        """Trigger a new 4 Ducks alignment analysis. Optionally scope to a campaign."""
        body = {}
        if campaign_id:
            body["campaign_id"] = campaign_id
        return await _safe_post(get_client, "/api/duck-reports/analyze", body or None)

    async def ff_roi_summary(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """ROI/tROI breakdown by campaign, ad, audience, LP."""
        return await _safe_get(get_client, "/api/roi/summary", _date_params(start_date, end_date))

    async def ff_visitors(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Visitor analytics with source/campaign filters."""
        return await _safe_get(get_client, "/api/visitors/", _date_params(start_date, end_date))

    async def ff_home_summary(
        start_date: str | None = None, end_date: str | None = None
    ) -> dict:
        """Dashboard KPIs + recent changelog."""
        return await _safe_get(get_client, "/api/home/summary", _date_params(start_date, end_date))

    tools = [
        (ToolDef(
            name="ff_portfolio_summary",
            description="Get FunnelFighters portfolio summary — spend, visitors, signups, activated, paying, revenue, tROI for a date range.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date (YYYY-MM-DD). Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date (YYYY-MM-DD). Default: today."},
            }},
            policy="auto_approve",
        ), ff_portfolio_summary),
        (ToolDef(
            name="ff_campaigns",
            description="List all campaigns with metrics for a date range.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_campaigns),
        (ToolDef(
            name="ff_campaign_detail",
            description="Deep dive into a specific campaign — hourly metrics, impression share, audience/device/geo breakdown.",
            parameters={"type": "object", "properties": {
                "campaign_id": {"type": "string", "description": "Campaign ID to inspect."},
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }, "required": ["campaign_id"]},
            policy="auto_approve",
        ), ff_campaign_detail),
        (ToolDef(
            name="ff_ads",
            description="List ads with performance metrics.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_ads),
        (ToolDef(
            name="ff_ad_detail",
            description="Ad creative details, funnel through-rate, versions, and agent action history.",
            parameters={"type": "object", "properties": {
                "ad_id": {"type": "string", "description": "Ad ID to inspect."},
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }, "required": ["ad_id"]},
            policy="auto_approve",
        ), ff_ad_detail),
        (ToolDef(
            name="ff_funnel",
            description="Full funnel waterfall: impressions → clicks → visitors → signups → activated → paying.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_funnel),
        (ToolDef(
            name="ff_cohorts",
            description="Weekly signup cohorts with conversion progression.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_cohorts),
        (ToolDef(
            name="ff_keywords",
            description="Keyword performance + search terms.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_keywords),
        (ToolDef(
            name="ff_wasted_spend",
            description="Wasted spend analysis — identify budget going to non-converting paths.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_wasted_spend),
        (ToolDef(
            name="ff_landing_pages",
            description="Landing page performance — signup rates, bounce rates, per-LP metrics.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_landing_pages),
        (ToolDef(
            name="ff_duck_reports",
            description="Get 4 Ducks alignment reports showing which ducks are misaligned.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_duck_reports),
        (ToolDef(
            name="ff_duck_analyze",
            description="Trigger a new 4 Ducks alignment analysis. Optionally scope to a specific campaign.",
            parameters={"type": "object", "properties": {
                "campaign_id": {"type": "string", "description": "Optional campaign ID to scope the analysis."},
            }},
            policy="auto_approve",
        ), ff_duck_analyze),
        (ToolDef(
            name="ff_roi_summary",
            description="ROI/tROI breakdown by campaign, ad, audience, and landing page.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_roi_summary),
        (ToolDef(
            name="ff_visitors",
            description="Visitor analytics with source/campaign filters.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_visitors),
        (ToolDef(
            name="ff_home_summary",
            description="Dashboard KPIs + recent changelog from FunnelFighters home.",
            parameters={"type": "object", "properties": {
                "start_date": {"type": "string", "description": "ISO date. Default: 28 days ago."},
                "end_date": {"type": "string", "description": "ISO date. Default: today."},
            }},
            policy="auto_approve",
        ), ff_home_summary),
    ]

    return tools
