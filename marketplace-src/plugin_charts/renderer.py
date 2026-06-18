"""Chart renderer — builds self-contained Chart.js HTML documents."""

from __future__ import annotations

import json
from typing import Any

CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"

PALETTE = [
    "#7c3aed", "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
    "#a855f7", "#06b6d4", "#f97316", "#ec4899", "#14b8a6",
    "#8b5cf6", "#6366f1", "#22c55e", "#eab308", "#f43f5e",
]


def render_chart(
    chart_type: str,
    labels: list[str],
    datasets: list[dict[str, Any]],
    title: str | None = None,
) -> str:
    """Return a self-contained HTML document that renders a Chart.js chart.

    Dark theme matching Luna's ink-900 palette. Responsive, animated,
    with hover tooltips.
    """
    ds_configs = []
    for i, ds in enumerate(datasets):
        color = ds.get("color") or PALETTE[i % len(PALETTE)]
        config: dict[str, Any] = {
            "label": ds.get("label", f"Dataset {i + 1}"),
            "data": ds.get("data", []),
            "borderColor": color,
            "backgroundColor": color + "33" if chart_type in ("line", "radar", "scatter") else _pie_colors(len(labels), i),
            "borderWidth": 2,
            "tension": 0.3,
            "fill": chart_type == "line",
            "pointRadius": 4 if chart_type in ("line", "scatter") else 0,
            "pointHoverRadius": 6,
        }
        if chart_type in ("pie", "doughnut"):
            config["backgroundColor"] = _pie_colors(len(labels), 0)
            config["borderColor"] = "#0a0a14"
            config["borderWidth"] = 2
        ds_configs.append(config)

    chart_config = {
        "type": chart_type,
        "data": {
            "labels": labels,
            "datasets": ds_configs,
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "animation": {"duration": 800, "easing": "easeOutQuart"},
            "plugins": {
                "legend": {
                    "display": len(datasets) > 1 or chart_type in ("pie", "doughnut"),
                    "position": "bottom",
                    "labels": {"color": "#a0a0b8", "padding": 16, "font": {"size": 12}},
                },
                "title": {
                    "display": bool(title),
                    "text": title or "",
                    "color": "#e2e0ef",
                    "font": {"size": 15, "weight": "600"},
                    "padding": {"bottom": 16},
                },
                "tooltip": {
                    "backgroundColor": "#1a1a2e",
                    "titleColor": "#e2e0ef",
                    "bodyColor": "#a0a0b8",
                    "borderColor": "rgba(255,255,255,0.1)",
                    "borderWidth": 1,
                    "cornerRadius": 8,
                    "padding": 10,
                },
            },
            "scales": _scales(chart_type),
        },
    }

    config_json = json.dumps(chart_config, default=str)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0f0f1a; font-family: system-ui, sans-serif; padding: 16px; }}
  .chart-wrap {{ position: relative; width: 100%; height: 280px; }}
</style>
</head>
<body>
<div class="chart-wrap">
  <canvas id="chart"></canvas>
</div>
<script src="{CHART_JS_CDN}"></script>
<script>
  const ctx = document.getElementById('chart').getContext('2d');
  new Chart(ctx, {config_json});
</script>
</body>
</html>"""


def _scales(chart_type: str) -> dict[str, Any]:
    if chart_type in ("pie", "doughnut", "radar"):
        return {}
    return {
        "x": {
            "ticks": {"color": "#6b6b8a", "font": {"size": 11}},
            "grid": {"color": "rgba(255,255,255,0.04)"},
        },
        "y": {
            "ticks": {"color": "#6b6b8a", "font": {"size": 11}},
            "grid": {"color": "rgba(255,255,255,0.04)"},
        },
    }


def _pie_colors(count: int, _offset: int = 0) -> list[str]:
    return [PALETTE[i % len(PALETTE)] + "cc" for i in range(count)]
