"""Database session and initialization."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models.db import Base


def get_database_url() -> str:
    """Resolve database URL — PostgreSQL in prod, SQLite locally."""
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # Render provides postgres:// but SQLAlchemy needs postgresql+asyncpg://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    # Local development fallback: SQLite
    db_path = Path(__file__).parent.parent / "data" / "marketplace.db"
    return f"sqlite+aiosqlite:///{db_path}"


DB_URL = get_database_url()

engine = create_async_engine(DB_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    if "sqlite" in DB_URL:
        Path(DB_URL.split("///")[1]).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        yield session
