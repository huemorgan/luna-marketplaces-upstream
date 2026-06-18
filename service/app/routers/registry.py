"""The marketplace protocol Luna consumes (static-shape, served from DB).

Luna's in-agent client (`luna/luna/plugins/install.py`) reads, under a
marketplace root URL:

    /.well-known/luna-marketplace.json   identity: {id, name, protocol_version}
    /index.json                          catalog: {marketplace, plugins:[...]}
    /plugins/{name}/{version}/artifact.zip

These routes live under `/mp/{slug}/`, so the URL handed to Luna is:
    https://<host>/mp/<slug>/

The hard rule: each plugin entry's `sha256` equals the hash of the served
artifact bytes, or Luna refuses to load. We store bytes content-addressed by
that exact hash, so they cannot drift.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..database import get_db
from ..models.db import Marketplace, Plugin, PluginVersion, UsageEvent, now_ts

router = APIRouter(prefix="/mp", tags=["registry"])

PROTOCOL_VERSION = "0"


async def _get_marketplace(slug: str, db: AsyncSession) -> Marketplace:
    result = await db.execute(select(Marketplace).where(Marketplace.slug == slug))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, f"marketplace '{slug}' not found")
    return mp


async def _latest_version(plugin_id: str, db: AsyncSession) -> PluginVersion | None:
    result = await db.execute(
        select(PluginVersion)
        .where(PluginVersion.plugin_id == plugin_id, PluginVersion.yanked == False)  # noqa: E712
        .order_by(PluginVersion.published_at.desc())
    )
    return result.scalars().first()


@router.get("/{slug}/.well-known/luna-marketplace.json")
async def identity(slug: str, db: AsyncSession = Depends(get_db)):
    mp = await _get_marketplace(slug, db)
    return JSONResponse({
        "id": mp.id,
        "name": mp.name,
        "protocol_version": PROTOCOL_VERSION,
    })


@router.get("/{slug}/index.json")
async def index(slug: str, db: AsyncSession = Depends(get_db)):
    mp = await _get_marketplace(slug, db)
    result = await db.execute(select(Plugin).where(Plugin.marketplace_id == mp.id))
    plugins = result.scalars().all()

    entries: list[dict] = []
    for p in plugins:
        pv = await _latest_version(p.id, db)
        if pv is None:
            continue
        manifest = pv.manifest_data or {}
        entries.append({
            "name": p.name,
            "version": pv.version,
            "description": p.description or manifest.get("description", ""),
            "sdk_version": str(manifest.get("sdk_version", "0")),
            "requires": pv.capabilities_required or manifest.get("requires", {}),
            "artifact": f"plugins/{p.name}/{pv.version}/artifact.zip",
            "sha256": pv.artifact_hash,
        })

    return JSONResponse({
        "marketplace": {"id": mp.id, "name": mp.name},
        "protocol_version": PROTOCOL_VERSION,
        "plugins": entries,
    })


@router.get("/{slug}/plugins/{name}/{version}/artifact.zip")
async def artifact(slug: str, name: str, version: str, db: AsyncSession = Depends(get_db)):
    mp = await _get_marketplace(slug, db)
    result = await db.execute(
        select(Plugin).where(Plugin.marketplace_id == mp.id, Plugin.name == name)
    )
    plugin = result.scalar_one_or_none()
    if not plugin:
        raise HTTPException(404, f"plugin '{name}' not found")

    ver_result = await db.execute(
        select(PluginVersion).where(
            PluginVersion.plugin_id == plugin.id, PluginVersion.version == version
        )
    )
    pv = ver_result.scalar_one_or_none()
    if not pv:
        raise HTTPException(404, f"version '{version}' not found")

    try:
        data = storage.read(pv.artifact_hash)
    except FileNotFoundError:
        raise HTTPException(410, "artifact bytes missing on disk")

    # Meter the download (best-effort; never block the fetch).
    try:
        plugin.download_count = (plugin.download_count or 0) + 1
        db.add(UsageEvent(
            org_id=mp.org_id,
            marketplace_id=mp.id,
            event_type="download",
            plugin_name=f"{plugin.namespace}/{plugin.name}",
            metadata_={"version": version},
            timestamp=now_ts(),
        ))
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()

    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}-{version}.zip"'},
    )
