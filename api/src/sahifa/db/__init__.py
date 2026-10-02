"""Database: declarative base, async engine and session factory (ADR-0003)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(url: str, application_name: str | None = None) -> AsyncEngine:
    """`application_name` names the connections in `pg_stat_activity` (the worker's, spec 008)."""
    connect_args = {"application_name": application_name} if application_name else {}
    return create_async_engine(
        url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args=connect_args
    )


class Database:
    """Holds the engine and session factory for the app's lifetime."""

    def __init__(self, url: str, application_name: str | None = None) -> None:
        self.engine = make_engine(url, application_name)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as s:
            yield s

    async def dispose(self) -> None:
        await self.engine.dispose()
