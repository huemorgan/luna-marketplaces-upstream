"""Plugin publishing and catalog API routes."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models.db import Marketplace, Org, OrgMember, Plugin, PluginVersion, User, UsageEvent, now_ts
from ..models.schemas import PluginResponse, PluginVersionResponse

router = APIRouter()

ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "data" / "artifacts"


@router.post("/marketplaces/{mp_slug}/publish")
async def publish_plugin(
    mp_slug: str,
    manifest: str = Form(...),
    artifact: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Publish a plugin version to a marketplace."""
    mp = await _get_marketplace_for_publisher(mp_slug, user, db)
    manifest_data = json.loads(manifest)

    name = manifest_data.get("name")
    namespace = manifest_data.get("namespace", mp.slug)
    version = manifest_data.get("version")
    if not name or not version:
        raise HTTPException(400, "Manifest must include name and version")

    # Read artifact and hash it
    artifact_bytes = await artifact.read()
    artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
    manifest_hash = hashlib.sha256(json.dumps(manifest_data).encode()).hexdigest()

    # Check immutability
    result = await db.execute(
        select(Plugin).where(Plugin.marketplace_id == mp.id, Plugin.name == name)
    )
    plugin = result.scalar_one_or_none()

    if plugin:
        # Check for duplicate version
        ver_result = await db.execute(
            select(PluginVersion).where(
                PluginVersion.plugin_id == plugin.id,
                PluginVersion.version == version,
            )
        )
        existing_ver = ver_result.scalar_one_or_none()
        if existing_ver:
            if existing_ver.artifact_hash != artifact_hash:
                raise HTTPException(
                    409, f"Version {version} already exists with different content (immutability rule)"
                )
            raise HTTPException(409, f"Version {version} already published")
    else:
        # Create plugin entry
        permissions = manifest_data.get("permissions", {})
        tools = permissions.get("tools", [])
        plugin = Plugin(
            id=str(uuid.uuid4()),
            marketplace_id=mp.id,
            name=name,
            namespace=namespace,
            description=manifest_data.get("description", ""),
            readme=manifest_data.get("readme", ""),
            tags=manifest_data.get("tags", []),
            license=manifest_data.get("license", "MIT"),
            icon_url=manifest_data.get("icon"),
            source_url=manifest_data.get("provenance", {}).get("source"),
            requires_tools=len(tools) > 0,
            requires_ui_iframe=permissions.get("ui_iframe", False),
            requires_settings_tab=permissions.get("settings_tab", False),
            requires_vault_access=permissions.get("vault_access", False),
            requires_egress=permissions.get("egress_hosts", []),
            tool_count=len(tools),
            tool_policies=tools,
        )
        db.add(plugin)

    # Update plugin metadata
    plugin.latest_version = version
    plugin.description = manifest_data.get("description", plugin.description)
    plugin.readme = manifest_data.get("readme", plugin.readme)
    plugin.tags = manifest_data.get("tags", plugin.tags)
    plugin.updated_at = now_ts()

    # Create version entry
    compat = manifest_data.get("compat", {})
    pv = PluginVersion(
        id=str(uuid.uuid4()),
        plugin_id=plugin.id,
        version=version,
        artifact_hash=artifact_hash,
        manifest_hash=manifest_hash,
        manifest_data=manifest_data,
        sdk_compat=compat.get("sdk", "^1.0"),
        capabilities_required=compat.get("requires", {}),
    )
    db.add(pv)

    # Store artifact
    artifact_dir = ARTIFACTS_DIR / mp.slug / name / version
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "artifact.zip").write_bytes(artifact_bytes)
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest_data, indent=2))

    # Record usage event
    db.add(UsageEvent(
        id=str(uuid.uuid4()),
        org_id=mp.org_id,
        marketplace_id=mp.id,
        event_type="publish",
        plugin_name=f"{namespace}/{name}",
        metadata={"version": version},
    ))

    await db.commit()
    return {"status": "published", "plugin": f"{namespace}/{name}", "version": version}


@router.get("/catalog/{mp_slug}", response_model=list[PluginResponse])
async def catalog(
    mp_slug: str,
    search: str | None = Query(None),
    tags: str | None = Query(None),
    license_filter: str | None = Query(None, alias="license"),
    requires_ui: bool | None = Query(None),
    requires_vault: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Browse the plugin catalog for a marketplace."""
    result = await db.execute(select(Marketplace).where(Marketplace.slug == mp_slug))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, "Marketplace not found")

    query = select(Plugin).where(Plugin.marketplace_id == mp.id)

    if search:
        query = query.where(
            or_(
                Plugin.name.contains(search),
                Plugin.description.contains(search),
            )
        )
    if license_filter:
        query = query.where(Plugin.license == license_filter)
    if requires_ui is not None:
        query = query.where(Plugin.requires_ui_iframe == requires_ui)
    if requires_vault is not None:
        query = query.where(Plugin.requires_vault_access == requires_vault)

    plugins_result = await db.execute(query)
    plugins = plugins_result.scalars().all()

    # Filter by tags in Python (JSON column)
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        plugins = [p for p in plugins if any(t in (p.tags or []) for t in tag_list)]

    return [
        PluginResponse(
            id=p.id,
            name=p.name,
            namespace=p.namespace,
            description=p.description,
            readme=p.readme or "",
            tags=p.tags or [],
            license=p.license,
            icon_url=p.icon_url,
            source_url=p.source_url,
            latest_version=p.latest_version,
            download_count=p.download_count,
            created_at=p.created_at,
            updated_at=p.updated_at,
            requires_tools=p.requires_tools,
            requires_ui_iframe=p.requires_ui_iframe,
            requires_settings_tab=p.requires_settings_tab,
            requires_vault_access=p.requires_vault_access,
            requires_egress=p.requires_egress or [],
            tool_count=p.tool_count,
            tool_policies=p.tool_policies or [],
            marketplace_slug=mp.slug,
            marketplace_name=mp.name,
        )
        for p in plugins
    ]


@router.get("/catalog/{mp_slug}/{plugin_name}", response_model=PluginResponse)
async def get_plugin(
    mp_slug: str,
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed plugin info."""
    result = await db.execute(select(Marketplace).where(Marketplace.slug == mp_slug))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, "Marketplace not found")

    plugin_result = await db.execute(
        select(Plugin).where(Plugin.marketplace_id == mp.id, Plugin.name == plugin_name)
    )
    p = plugin_result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Plugin not found")

    return PluginResponse(
        id=p.id,
        name=p.name,
        namespace=p.namespace,
        description=p.description,
        readme=p.readme or "",
        tags=p.tags or [],
        license=p.license,
        icon_url=p.icon_url,
        source_url=p.source_url,
        latest_version=p.latest_version,
        download_count=p.download_count,
        created_at=p.created_at,
        updated_at=p.updated_at,
        requires_tools=p.requires_tools,
        requires_ui_iframe=p.requires_ui_iframe,
        requires_settings_tab=p.requires_settings_tab,
        requires_vault_access=p.requires_vault_access,
        requires_egress=p.requires_egress or [],
        tool_count=p.tool_count,
        tool_policies=p.tool_policies or [],
        marketplace_slug=mp.slug,
        marketplace_name=mp.name,
    )


@router.get("/catalog/{mp_slug}/{plugin_name}/versions", response_model=list[PluginVersionResponse])
async def get_plugin_versions(
    mp_slug: str,
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Marketplace).where(Marketplace.slug == mp_slug))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, "Marketplace not found")

    plugin_result = await db.execute(
        select(Plugin).where(Plugin.marketplace_id == mp.id, Plugin.name == plugin_name)
    )
    p = plugin_result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Plugin not found")

    versions_result = await db.execute(
        select(PluginVersion).where(PluginVersion.plugin_id == p.id).order_by(PluginVersion.published_at.desc())
    )
    versions = versions_result.scalars().all()

    return [
        PluginVersionResponse(
            id=v.id,
            version=v.version,
            artifact_hash=v.artifact_hash,
            sdk_compat=v.sdk_compat,
            capabilities_required=v.capabilities_required or {},
            published_at=v.published_at,
            yanked=v.yanked,
        )
        for v in versions
    ]


async def _get_marketplace_for_publisher(mp_slug: str, user: User, db: AsyncSession) -> Marketplace:
    result = await db.execute(select(Marketplace).where(Marketplace.slug == mp_slug))
    mp = result.scalar_one_or_none()
    if not mp:
        raise HTTPException(404, "Marketplace not found")

    membership = await db.execute(
        select(OrgMember).where(OrgMember.org_id == mp.org_id, OrgMember.user_id == user.id)
    )
    member = membership.scalar_one_or_none()
    if not member or member.role not in ("owner", "publisher"):
        raise HTTPException(403, "Must be owner or publisher to publish plugins")

    return mp
