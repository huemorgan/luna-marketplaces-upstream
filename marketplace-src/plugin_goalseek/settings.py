"""Owner settings — the phase-05 config section.

One store, two doors: the Settings tab (routes.py) and the agent's generic
``manage_config`` tool (via the config registry) read and write the SAME
rows, so a change in either place is authoritative. Values are stored as
``{"v": ...}`` JSON so ints/bools/strings round-trip through JSONB cleanly.

``auto_approve_agent_goals`` is special: it mirrors the phase-02 grant row
(the actual authority), so reading consults GrantStore and writing
grants/revokes through it — one source of truth, no drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from .models import SettingRow

DEFAULTS: dict[str, Any] = {
    "max_active_goals": 5,
    "default_autonomy_level": 3,
    "quiet_hours": "",
    "tuning_warn_hits": 3,
    "tuning_warn_rate": 0.25,
}

# What each field means, for the agent (config registry) and the Settings tab.
FIELD_SCHEMA: dict[str, dict[str, Any]] = {
    "max_active_goals": {
        "type": "integer", "min": 1, "max": 20, "default": 5,
        "description": "How many goals may be active at once; new goals beyond the cap open parked.",
    },
    "default_autonomy_level": {
        "type": "integer", "enum": [1, 2, 3], "default": 3,
        "description": "Autonomy for new goals: 1 observe & advise, 2 act with approval, 3 act freely.",
    },
    "auto_approve_agent_goals": {
        "type": "boolean", "default": False,
        "description": "Let Luna open her own goals without an approval card (mirrors the standing grant).",
    },
    "quiet_hours": {
        "type": "string", "default": "",
        "description": "Window when goal outreach must not happen, e.g. '22-8'. Empty = none.",
    },
    "tuning_warn_hits": {
        "type": "integer", "default": 3,
        "description": "Policy blocks on one gate before the tuning meter turns amber.",
    },
    "tuning_warn_rate": {
        "type": "number", "default": 0.25,
        "description": "Blocked/total effect ratio that flags a goal as poorly tuned.",
    },
}


def _coerce(key: str, value: Any) -> Any:
    spec = FIELD_SCHEMA.get(key) or {}
    t = spec.get("type")
    try:
        if t == "integer":
            value = int(value)
        elif t == "number":
            value = float(value)
        elif t == "boolean":
            value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
        elif t == "string":
            value = str(value)
    except (TypeError, ValueError):
        raise ValueError(f"setting '{key}' must be a {t}, got {value!r}") from None
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f"setting '{key}' must be one of {spec['enum']}, got {value!r}")
    if "min" in spec and value < spec["min"]:
        raise ValueError(f"setting '{key}' must be >= {spec['min']}")
    if "max" in spec and value > spec["max"]:
        raise ValueError(f"setting '{key}' must be <= {spec['max']}")
    return value


class SettingsStore:
    def __init__(self, session_factory, grant_store=None) -> None:
        self._sf = session_factory
        self._grants = grant_store

    async def get_all(self) -> dict[str, Any]:
        out = dict(DEFAULTS)
        async with self._sf() as s:
            rows = (await s.execute(select(SettingRow))).scalars().all()
            for r in rows:
                if r.key in FIELD_SCHEMA:
                    out[r.key] = (r.value or {}).get("v")
        if self._grants is not None:
            out["auto_approve_agent_goals"] = await self._grants.is_active(
                "auto_approve_agent_goals"
            )
        else:
            out.setdefault("auto_approve_agent_goals", False)
        return out

    async def get(self, key: str) -> Any:
        return (await self.get_all()).get(key, DEFAULTS.get(key))

    async def set_many(self, changes: dict[str, Any]) -> dict[str, Any]:
        unknown = [k for k in changes if k not in FIELD_SCHEMA]
        if unknown:
            raise ValueError(f"unknown settings: {unknown} (valid: {list(FIELD_SCHEMA)})")
        coerced = {k: _coerce(k, v) for k, v in changes.items()}

        grant_flip = coerced.pop("auto_approve_agent_goals", None)
        if coerced:
            async with self._sf() as s:
                for k, v in coerced.items():
                    row = await s.get(SettingRow, k)
                    if row is None:
                        s.add(SettingRow(key=k, value={"v": v}))
                    else:
                        row.value = {"v": v}
                await s.commit()
        if grant_flip is not None and self._grants is not None:
            active = await self._grants.is_active("auto_approve_agent_goals")
            if grant_flip and not active:
                await self._grants.grant("auto_approve_agent_goals", granted_by="owner")
            elif not grant_flip and active:
                await self._grants.revoke("auto_approve_agent_goals")
        return await self.get_all()


@dataclass
class GoalseekConfigSection:
    """Duck-typed twin of core's ConfigSection (luna_sdk does not export it;
    the registry only reads attributes, so a same-shaped object registers
    fine). Keeps the package luna_sdk-only."""

    id: str
    label: str
    description: str
    reader: Any
    writer: Any
    schema: Any
    plugin: str = ""
    readonly_fields: list[str] = field(default_factory=list)


def register_config_section(ctx, store: SettingsStore, plugin_name: str) -> bool:
    """Best-effort: older cores without a config registry just skip it."""
    register = getattr(ctx, "register_config_section", None)
    if not callable(register):
        return False

    async def _read() -> dict[str, Any]:
        return await store.get_all()

    async def _write(changes: dict[str, Any]) -> dict[str, Any]:
        return await store.set_many(changes)

    try:
        register(
            GoalseekConfigSection(
                id="goalseek",
                label="Goals",
                description=(
                    "Goal-seek settings: concurrency cap, default autonomy for new "
                    "goals, self-opened-goal auto-approval, quiet hours, tuning "
                    "thresholds."
                ),
                reader=_read,
                writer=_write,
                schema=lambda: dict(FIELD_SCHEMA),
                plugin=plugin_name,
            )
        )
        return True
    except Exception:  # noqa: BLE001 — a registry quirk must not fail on_load
        return False
