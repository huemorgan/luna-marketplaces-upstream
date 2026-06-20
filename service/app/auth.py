"""Authentication utilities — JWT + password hashing."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import hashlib

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models.db import User

import os

SECRET_KEY = os.environ.get("JWT_SECRET", "luna-marketplaces-dev-secret-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 72

security = HTTPBearer(auto_error=False)

# Global editor allow list: emails permitted to publish to ANY catalog (including
# `official`), independent of org/account membership. Set via the GLOBAL_EDITORS
# env var as a comma-separated list of emails. Used for catalogs (like official)
# that have no real account behind them.
GLOBAL_EDITORS: set[str] = {
    e.strip().lower()
    for e in os.environ.get("GLOBAL_EDITORS", "").split(",")
    if e.strip()
}


def is_global_editor(user: User) -> bool:
    """True if the user is on the global editor allow list (by email)."""
    return bool(user.email) and user.email.lower() in GLOBAL_EDITORS


def hash_password(password: str) -> str:
    return hashlib.sha256(f"luna-mp-salt:{password}".encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
