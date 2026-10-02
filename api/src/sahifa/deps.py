"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Database
from .settings import Settings


def settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def session(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database = request.app.state.db
    async with db.sessions() as s:
        yield s
