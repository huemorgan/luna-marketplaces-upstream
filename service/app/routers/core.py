"""API routes for accounts, orgs, and marketplaces."""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from nacl.signing import SigningKey
from nacl.encoding import HexEncoder
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_access_token, get_current_user, hash_password, verify_password
from ..database import get_db
from ..models.db import Marketplace, Org, OrgMember, Plugin, User, UsageEvent, now_ts
from ..models.schemas import (
    LoginRequest,
    MarketplaceCreate,
    MarketplaceResponse,
    OrgCreate,
    OrgResponse,
    TokenResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter()


@router.post("/auth/signup", response_model=UserResponse)
async def signup(data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        email=data.email,
        username=data.username,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse(id=user.id, email=user.email, username=user.username, created_at=user.created_at)


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.post("/orgs", response_model=OrgResponse)
async def create_org(
    data: OrgCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(Org).where(Org.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Org slug already taken")

    org = Org(id=str(uuid.uuid4()), name=data.name, slug=data.slug)
    db.add(org)

    member = OrgMember(
        id=str(uuid.uuid4()), org_id=org.id, user_id=user.id, role="owner"
    )
    db.add(member)
    await db.commit()
    await db.refresh(org)
    return OrgResponse(id=org.id, name=org.name, slug=org.slug, plan=org.plan, created_at=org.created_at)


@router.get("/orgs", response_model=list[OrgResponse])
async def list_orgs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Org).join(OrgMember).where(OrgMember.user_id == user.id)
    )
    return [
        OrgResponse(id=o.id, name=o.name, slug=o.slug, plan=o.plan, created_at=o.created_at)
        for o in result.scalars()
    ]


@router.post("/orgs/{org_slug}/marketplaces", response_model=MarketplaceResponse)
async def create_marketplace(
    org_slug: str,
    data: MarketplaceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_for_user(org_slug, user, db, min_role="owner")

    existing = await db.execute(select(Marketplace).where(Marketplace.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Marketplace slug already taken")

    # Generate signing keypair
    sk = SigningKey.generate()
    pub_hex = sk.verify_key.encode(encoder=HexEncoder).decode()
    priv_hex = sk.encode(encoder=HexEncoder).decode()

    # Generate access token for private marketplaces
    access_token = secrets.token_urlsafe(32) if data.visibility == "private" else None

    mp = Marketplace(
        id=str(uuid.uuid4()),
        org_id=org.id,
        name=data.name,
        slug=data.slug,
        description=data.description,
        visibility=data.visibility,
        signing_key_public=pub_hex,
        signing_key_private_encrypted=priv_hex,
        access_token=access_token,
    )
    db.add(mp)
    await db.commit()
    await db.refresh(mp)

    return MarketplaceResponse(
        id=mp.id,
        name=mp.name,
        slug=mp.slug,
        description=mp.description,
        visibility=mp.visibility,
        signing_key_public=mp.signing_key_public,
        access_token=mp.access_token,
        created_at=mp.created_at,
    )


@router.get("/orgs/{org_slug}/marketplaces", response_model=list[MarketplaceResponse])
async def list_marketplaces(
    org_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_for_user(org_slug, user, db)
    result = await db.execute(
        select(Marketplace).where(Marketplace.org_id == org.id)
    )
    mps = result.scalars().all()
    responses = []
    for mp in mps:
        count_result = await db.execute(
            select(func.count(Plugin.id)).where(Plugin.marketplace_id == mp.id)
        )
        count = count_result.scalar() or 0
        responses.append(
            MarketplaceResponse(
                id=mp.id,
                name=mp.name,
                slug=mp.slug,
                description=mp.description,
                visibility=mp.visibility,
                signing_key_public=mp.signing_key_public,
                access_token=mp.access_token if mp.visibility == "private" else None,
                created_at=mp.created_at,
                plugin_count=count,
            )
        )
    return responses


async def _get_org_for_user(
    org_slug: str, user: User, db: AsyncSession, min_role: str | None = None
) -> Org:
    result = await db.execute(select(Org).where(Org.slug == org_slug))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Org not found")

    membership = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org.id, OrgMember.user_id == user.id)
    )
    member = membership.scalar_one_or_none()
    if not member:
        raise HTTPException(403, "Not a member of this org")

    if min_role:
        role_hierarchy = ["viewer", "reviewer", "publisher", "owner"]
        if role_hierarchy.index(member.role) < role_hierarchy.index(min_role):
            raise HTTPException(403, f"Requires {min_role} role")

    return org
