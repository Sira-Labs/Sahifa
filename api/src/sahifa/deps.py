"""FastAPI dependencies shared by the routers."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.access import Access, current_access
from .db import WORKSPACES, Database
from .settings import Settings


def settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def access(request: Request) -> Access:
    """The caller's workspaces and roles (spec 016)."""
    return await current_access(request)


async def session(request: Request, caller: Access = Depends(access)) -> AsyncIterator[AsyncSession]:
    """A session that sees the caller's workspaces only, under row-level security (spec 016)."""
    db: Database = request.app.state.db
    async with db.sessions() as s:
        s.info[WORKSPACES] = tuple(caller.workspaces)
        yield s


async def unscoped_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session that sees no workspace-owned row: for routes that read none (health)."""
    db: Database = request.app.state.db
    async with db.sessions() as s:
        yield s
