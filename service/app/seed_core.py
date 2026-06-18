"""Seed core (repo-owned) plugins into the official marketplace on startup.

Core plugins live as source under `marketplace-src/` and are packaged
deterministically and upserted into the `official` marketplace every boot.
Idempotent: a version already present with the same sha256 is skipped; a
re-publish with different bytes for an existing version is refused (immutability).

Everything else (third-party plugins) is added at runtime via the upload API —
same DB tables, different ingestion path.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import storage
from .auth import hash_password
from .database import async_session
from .packaging import package_source
from .models.db import (
    Artifact,
    Marketplace,
    Org,
    OrgMember,
    Plugin,
    PluginVersion,
    User,
    now_ts,
)

# Stable identifiers so Luna's pinned marketplace id never changes across deploys.
OFFICIAL_MP_ID = "00000000-0000-4000-8000-000000000001"
OFFICIAL_MP_SLUG = "official"
OFFICIAL_MP_NAME = "Luna Official (dev)"
OFFICIAL_ORG_ID = "00000000-0000-4000-8000-0000000000a1"
OFFICIAL_ORG_SLUG = "luna-official"
CORE_USER_ID = "00000000-0000-4000-8000-0000000000b1"
CORE_USER_EMAIL = "core@luna-marketplaces.local"


def _marketplace_src() -> Path:
    env = os.environ.get("MARKETPLACE_SRC")
    if env:
        return Path(env)
    # service/app/seed_core.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2] / "marketplace-src"


async def _ensure_official(db: AsyncSession) -> Marketplace:
    user = await db.get(User, CORE_USER_ID)
    if user is None:
        user = User(
            id=CORE_USER_ID,
            email=CORE_USER_EMAIL,
            username="luna-core",
            password_hash=hash_password(uuid.uuid4().hex),
            created_at=now_ts(),
        )
        db.add(user)

    org = await db.get(Org, OFFICIAL_ORG_ID)
    if org is None:
        org = Org(id=OFFICIAL_ORG_ID, name="Luna Official", slug=OFFICIAL_ORG_SLUG, created_at=now_ts())
        db.add(org)
        db.add(OrgMember(id=str(uuid.uuid4()), org_id=OFFICIAL_ORG_ID, user_id=CORE_USER_ID, role="owner"))

    mp = await db.get(Marketplace, OFFICIAL_MP_ID)
    if mp is None:
        mp = Marketplace(
            id=OFFICIAL_MP_ID,
            org_id=OFFICIAL_ORG_ID,
            name=OFFICIAL_MP_NAME,
            slug=OFFICIAL_MP_SLUG,
            description="First-party plugins maintained in the luna-marketplaces repo.",
            visibility="public",
            created_at=now_ts(),
        )
        db.add(mp)

    await db.flush()
    return mp


def _tools_from_manifest(manifest: dict) -> list[dict]:
    return manifest.get("tools", []) or []


async def _upsert_plugin(db: AsyncSession, mp: Marketplace, manifest: dict, sha256: str, zip_bytes: bytes) -> str:
    name = manifest["name"]
    version = str(manifest["version"])
    tools = _tools_from_manifest(manifest)

    result = await db.execute(
        select(Plugin).where(Plugin.marketplace_id == mp.id, Plugin.name == name)
    )
    plugin = result.scalar_one_or_none()
    if plugin is None:
        plugin = Plugin(
            id=str(uuid.uuid4()),
            marketplace_id=mp.id,
            name=name,
            namespace=mp.slug,
            description=manifest.get("description", ""),
            readme=manifest.get("readme", ""),
            tags=manifest.get("tags", []),
            license=manifest.get("license", "MIT"),
            requires_tools=len(tools) > 0,
            tool_count=len(tools),
            tool_policies=tools,
            created_at=now_ts(),
            updated_at=now_ts(),
        )
        db.add(plugin)
        await db.flush()
    else:
        plugin.description = manifest.get("description", plugin.description)
        plugin.readme = manifest.get("readme", plugin.readme)
        plugin.tags = manifest.get("tags", plugin.tags)
        plugin.tool_count = len(tools)
        plugin.tool_policies = tools
        plugin.requires_tools = len(tools) > 0
        plugin.updated_at = now_ts()

    # Version immutability check.
    ver_result = await db.execute(
        select(PluginVersion).where(
            PluginVersion.plugin_id == plugin.id, PluginVersion.version == version
        )
    )
    existing = ver_result.scalar_one_or_none()
    if existing is not None:
        if existing.artifact_hash != sha256:
            return f"SKIP {name} {version}: already published with different bytes (immutable)"
        # Make sure the bytes are on disk (disk may have been recreated).
        if not storage.exists(sha256):
            storage.store(sha256, zip_bytes)
        return f"ok {name} {version} (unchanged)"

    storage.store(sha256, zip_bytes)
    if await db.get(Artifact, sha256) is None:
        db.add(Artifact(sha256=sha256, size=len(zip_bytes), created_at=now_ts()))

    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    db.add(PluginVersion(
        id=str(uuid.uuid4()),
        plugin_id=plugin.id,
        version=version,
        artifact_hash=sha256,
        manifest_hash=manifest_hash,
        manifest_data=manifest,
        sdk_compat=str(manifest.get("sdk_version", "0")),
        capabilities_required=manifest.get("requires", {}),
        published_at=now_ts(),
    ))
    plugin.latest_version = version
    plugin.updated_at = now_ts()
    return f"seeded {name} {version} sha256={sha256[:12]}"


async def seed_core_plugins() -> list[str]:
    """Package every plugin under marketplace-src/ and upsert into official."""
    src = _marketplace_src()
    log: list[str] = []
    if not src.exists():
        return [f"no marketplace-src at {src}"]

    async with async_session() as db:
        mp = await _ensure_official(db)
        for pkg in sorted(p for p in src.iterdir() if p.is_dir()):
            if not (pkg / "__init__.py").exists() or not (pkg / "luna-plugin.toml").exists():
                continue
            try:
                zip_bytes, sha256, manifest = package_source(pkg)
                log.append(await _upsert_plugin(db, mp, manifest, sha256, zip_bytes))
            except Exception as e:  # noqa: BLE001
                log.append(f"ERROR {pkg.name}: {e}")
        await db.commit()
    return log
