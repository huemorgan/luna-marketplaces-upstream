"""Bundle management + browse API routes.

A bundle is a curated, marketed group of EXISTING plugins in one marketplace.
Bundle versions pin exact plugin versions; a plugin releasing a new version
never mutates a bundle — editors publish a new bundle version deliberately.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models.db import Bundle, BundleVersion, Marketplace, Plugin, PluginVersion, User, now_ts
from ..models.schemas import (
    BundleCreate,
    BundleItem,
    BundleItemResolved,
    BundleResponse,
    BundleUpdate,
    BundleVersionCreate,
    BundleVersionResponse,
    YankRequest,
)
from .plugins import _get_marketplace_for_publisher

router = APIRouter()


async def _validate_items(db: AsyncSession, mp: Marketplace, items: list[BundleItem]) -> None:
    """Every pinned (plugin, version) must exist in this marketplace."""
    if not items:
        raise HTTPException(400, "a bundle must contain at least one plugin")
    seen: set[str] = set()
    for item in items:
        if item.plugin_name in seen:
            raise HTTPException(400, f"duplicate plugin in bundle: {item.plugin_name}")
        seen.add(item.plugin_name)
        result = await db.execute(
            select(Plugin).where(Plugin.marketplace_id == mp.id, Plugin.name == item.plugin_name)
        )
        plugin = result.scalar_one_or_none()
        if not plugin:
            raise HTTPException(400, f"plugin '{item.plugin_name}' not found in this marketplace")
        ver = await db.execute(
            select(PluginVersion).where(
                PluginVersion.plugin_id == plugin.id, PluginVersion.version == item.version
            )
        )
        if not ver.scalar_one_or_none():
            raise HTTPException(
                400, f"plugin '{item.plugin_name}' has no version '{item.version}'"
            )


async def _resolve_items(db: AsyncSession, mp: Marketplace, items: list[dict]) -> list[BundleItemResolved]:
    """Enrich raw pins with member plugin catalog state (for browse/manage UIs)."""
    resolved: list[BundleItemResolved] = []
    for item in items or []:
        result = await db.execute(
            select(Plugin).where(
                Plugin.marketplace_id == mp.id, Plugin.name == item.get("plugin_name")
            )
        )
        plugin = result.scalar_one_or_none()
        resolved.append(BundleItemResolved(
            plugin_name=item.get("plugin_name", ""),
            version=item.get("version", ""),
            description=(plugin.description if plugin else ""),
            icon_url=(plugin.icon_url if plugin else None),
            latest_available=(plugin.latest_version if plugin else None),
            exists=plugin is not None,
        ))
    return resolved


async def _get_bundle(db: AsyncSession, mp: Marketplace, name: str) -> Bundle:
    result = await db.execute(
        select(Bundle).where(Bundle.marketplace_id == mp.id, Bundle.name == name)
    )
    bundle = result.scalar_one_or_none()
    if not bundle:
        raise HTTPException(404, "Bundle not found")
    return bundle


async def pick_latest_bundle_version(db: AsyncSession, bundle: Bundle) -> BundleVersion | None:
    """The bundle version to serve: the `latest_version` pointer if it's live,
    else the newest non-yanked one. (published_at is second-granular, so the
    pointer is the tiebreaker for versions published within the same second.)
    """
    result = await db.execute(
        select(BundleVersion)
        .where(BundleVersion.bundle_id == bundle.id, BundleVersion.yanked == False)  # noqa: E712
        .order_by(BundleVersion.published_at.desc())
    )
    versions = list(result.scalars().all())
    if not versions:
        return None
    for v in versions:
        if v.version == bundle.latest_version:
            return v
    return versions[0]


async def _latest_items(db: AsyncSession, bundle: Bundle) -> list[dict]:
    """Pin set of the latest live version (empty if none)."""
    bv = await pick_latest_bundle_version(db, bundle)
    return list(bv.items or []) if bv else []


async def _bundle_response(db: AsyncSession, mp: Marketplace, bundle: Bundle) -> BundleResponse:
    items = await _latest_items(db, bundle)
    return BundleResponse(
        id=bundle.id,
        name=bundle.name,
        title=bundle.title or bundle.name,
        description=bundle.description or "",
        readme=bundle.readme or "",
        tags=bundle.tags or [],
        icon_url=bundle.icon_url,
        latest_version=bundle.latest_version,
        download_count=bundle.download_count or 0,
        created_at=bundle.created_at,
        updated_at=bundle.updated_at,
        items=await _resolve_items(db, mp, items),
        marketplace_slug=mp.slug,
        marketplace_name=mp.name,
    )


# ---------------------------------------------------------------------------
# Management (editor-gated)
# ---------------------------------------------------------------------------

@router.post("/marketplaces/{mp_slug}/bundles", response_model=BundleResponse)
async def create_bundle(
    mp_slug: str,
    data: BundleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a bundle together with its first pinned version."""
    mp = await _get_marketplace_for_publisher(mp_slug, user, db)

    existing = await db.execute(
        select(Bundle).where(Bundle.marketplace_id == mp.id, Bundle.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"bundle '{data.name}' already exists")

    await _validate_items(db, mp, data.items)

    bundle = Bundle(
        id=str(uuid.uuid4()),
        marketplace_id=mp.id,
        name=data.name,
        title=data.title,
        description=data.description,
        readme=data.readme,
        tags=data.tags,
        icon_url=data.icon_url,
        latest_version=data.version,
    )
    db.add(bundle)
    db.add(BundleVersion(
        id=str(uuid.uuid4()),
        bundle_id=bundle.id,
        version=data.version,
        items=[i.model_dump() for i in data.items],
    ))
    await db.commit()
    await db.refresh(bundle)
    return await _bundle_response(db, mp, bundle)


@router.patch("/marketplaces/{mp_slug}/bundles/{bundle_name}", response_model=BundleResponse)
async def update_bundle(
    mp_slug: str,
    bundle_name: str,
    data: BundleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit bundle marketing metadata (title, description, readme, tags, image)."""
    mp = await _get_marketplace_for_publisher(mp_slug, user, db)
    bundle = await _get_bundle(db, mp, bundle_name)

    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(bundle, key, value)
    if fields:
        bundle.updated_at = now_ts()
    await db.commit()
    await db.refresh(bundle)
    return await _bundle_response(db, mp, bundle)


@router.post("/marketplaces/{mp_slug}/bundles/{bundle_name}/versions", response_model=BundleVersionResponse)
async def publish_bundle_version(
    mp_slug: str,
    bundle_name: str,
    data: BundleVersionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Publish a new bundle version with an updated pin set.

    This is THE deliberate action that moves a bundle to newer plugin versions.
    Versions are immutable: republishing an existing version is rejected.
    """
    mp = await _get_marketplace_for_publisher(mp_slug, user, db)
    bundle = await _get_bundle(db, mp, bundle_name)

    existing = await db.execute(
        select(BundleVersion).where(
            BundleVersion.bundle_id == bundle.id, BundleVersion.version == data.version
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"bundle version {data.version} already published (immutability rule)")

    await _validate_items(db, mp, data.items)

    bv = BundleVersion(
        id=str(uuid.uuid4()),
        bundle_id=bundle.id,
        version=data.version,
        items=[i.model_dump() for i in data.items],
    )
    db.add(bv)
    bundle.latest_version = data.version
    bundle.updated_at = now_ts()
    await db.commit()
    await db.refresh(bv)
    return BundleVersionResponse(
        id=bv.id,
        version=bv.version,
        items=[BundleItem(**i) for i in bv.items],
        published_at=bv.published_at,
        yanked=bv.yanked,
    )


@router.delete("/marketplaces/{mp_slug}/bundles/{bundle_name}")
async def delete_bundle(
    mp_slug: str,
    bundle_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a bundle and all its versions. Member plugins are untouched."""
    mp = await _get_marketplace_for_publisher(mp_slug, user, db)
    bundle = await _get_bundle(db, mp, bundle_name)

    versions = await db.execute(select(BundleVersion).where(BundleVersion.bundle_id == bundle.id))
    for v in versions.scalars():
        await db.delete(v)
    await db.delete(bundle)
    await db.commit()
    return {"status": "deleted", "bundle": f"{mp.slug}/{bundle_name}"}


@router.post("/marketplaces/{mp_slug}/bundles/{bundle_name}/versions/{version}/yank")
async def yank_bundle_version(
    mp_slug: str,
    bundle_name: str,
    version: str,
    data: YankRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Yank (hide) or un-yank a bundle version."""
    mp = await _get_marketplace_for_publisher(mp_slug, user, db)
    bundle = await _get_bundle(db, mp, bundle_name)

    result = await db.execute(
        select(BundleVersion).where(
            BundleVersion.bundle_id == bundle.id, BundleVersion.version == version
        )
    )
    bv = result.scalar_one_or_none()
    if not bv:
        raise HTTPException(404, "Version not found")
    bv.yanked = data.yanked
    await db.commit()
    return {"status": "yanked" if data.yanked else "unyanked", "version": version}


# ---------------------------------------------------------------------------
# Browse (public)
# ---------------------------------------------------------------------------

@router.get("/catalog/{mp_slug}/bundles", response_model=list[BundleResponse])
async def list_bundles(mp_slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Marketplace).where(Marketplace.slug == mp_slug))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, "Marketplace not found")

    bundles_result = await db.execute(select(Bundle).where(Bundle.marketplace_id == mp.id))
    return [await _bundle_response(db, mp, b) for b in bundles_result.scalars().all()]


@router.get("/catalog/{mp_slug}/bundles/{bundle_name}", response_model=BundleResponse)
async def get_bundle_detail(mp_slug: str, bundle_name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Marketplace).where(Marketplace.slug == mp_slug))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, "Marketplace not found")
    bundle = await _get_bundle(db, mp, bundle_name)
    return await _bundle_response(db, mp, bundle)


@router.get("/catalog/{mp_slug}/bundles/{bundle_name}/versions", response_model=list[BundleVersionResponse])
async def get_bundle_versions(mp_slug: str, bundle_name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Marketplace).where(Marketplace.slug == mp_slug))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, "Marketplace not found")
    bundle = await _get_bundle(db, mp, bundle_name)

    versions_result = await db.execute(
        select(BundleVersion)
        .where(BundleVersion.bundle_id == bundle.id)
        .order_by(BundleVersion.published_at.desc())
    )
    return [
        BundleVersionResponse(
            id=v.id,
            version=v.version,
            items=[BundleItem(**i) for i in (v.items or [])],
            published_at=v.published_at,
            yanked=v.yanked,
        )
        for v in versions_result.scalars().all()
    ]
