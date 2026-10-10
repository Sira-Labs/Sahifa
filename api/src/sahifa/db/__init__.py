"""Database: declarative base, async engine and session factories (ADR-0003).

Row-level security (spec 016, migration 0008) decides which rows a transaction sees from two
transaction-local settings, applied when each transaction begins:

- `sessions`: request sessions. They see the workspaces in `session.info[WORKSPACES]`, set by
  the request's access (`deps.session`); without it they see nothing (fail closed).
- `system`: jobs (worker, scheduler, reaper, upload clean-up, start-up registration). They see
  every workspace.

Each transaction also switches to the role `sahifa_app` when the login is a member of it, because
a superuser login bypasses row-level security and a role switched to does not.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, SessionTransaction


class Base(DeclarativeBase):
    pass


APP_ROLE = "sahifa_app"
WORKSPACES = "sahifa_workspaces"
SYSTEM = "sahifa_system"
_ROLE_CACHE = "sahifa_app_role"

_SCOPE = text(
    "SELECT set_config('sahifa.system', :system, true), set_config('sahifa.workspaces', :workspaces, true)"
)
_HAS_ROLE = text(
    "SELECT EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname = :role"
    " AND pg_has_role(session_user, r.oid, 'MEMBER'))"
)
_SET_ROLE = text(f"SET LOCAL ROLE {APP_ROLE}")
_BYPASS = text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = :role")


class ScopedSession(Session):
    """The sync session behind every `AsyncSession`; carries the scope listener below."""


def scope_of(info: dict[str, Any]) -> tuple[str, str]:
    """The values of `sahifa.system` and `sahifa.workspaces` for a session's `info`."""
    if info.get(SYSTEM):
        return "on", ""
    workspaces: Iterable[uuid.UUID] = info.get(WORKSPACES, ())
    return "", ",".join(str(w) for w in workspaces)


def has_app_role(connection: Connection) -> bool:
    """Whether this login may switch to `sahifa_app`, cached per database connection."""
    cached = connection.info.get(_ROLE_CACHE)
    if cached is None:
        cached = bool(connection.execute(_HAS_ROLE, {"role": APP_ROLE}).scalar())
        connection.info[_ROLE_CACHE] = cached
    return bool(cached)


@event.listens_for(ScopedSession, "after_begin")
def _apply_scope(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    """At each transaction start: the role switch, then the scope. Both end with the
    transaction, so a pooled connection never carries one request's scope into the next."""
    if has_app_role(connection):
        connection.execute(_SET_ROLE)
    system, workspaces = scope_of(session.info)
    connection.execute(_SCOPE, {"system": system, "workspaces": workspaces})


async def add_to_scope(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """Let a request session see a workspace created in it: now, and in its later transactions."""
    if session.info.get(SYSTEM):
        return
    session.info[WORKSPACES] = (*session.info.get(WORKSPACES, ()), workspace_id)
    _, workspaces = scope_of(session.info)
    await session.execute(text("SELECT set_config('sahifa.workspaces', :w, true)"), {"w": workspaces})


def make_engine(url: str, application_name: str | None = None) -> AsyncEngine:
    """`application_name` names the connections in `pg_stat_activity` (the worker's, spec 008)."""
    connect_args = {"application_name": application_name} if application_name else {}
    return create_async_engine(
        url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args=connect_args
    )


class Database:
    """Holds the engine and the two session factories for the app's lifetime."""

    def __init__(self, url: str, application_name: str | None = None) -> None:
        self.engine = make_engine(url, application_name)
        self.sessions = async_sessionmaker(
            self.engine, expire_on_commit=False, sync_session_class=ScopedSession
        )
        self.system = async_sessionmaker(
            self.engine, expire_on_commit=False, sync_session_class=ScopedSession, info={SYSTEM: True}
        )

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as s:
            yield s

    async def bypasses_rls(self) -> bool:
        """Whether row-level security would not bind the API: the role its transactions run as
        (`sahifa_app` when the login can switch to it, else the login) is a superuser or has
        BYPASSRLS."""
        async with self.engine.connect() as conn:
            switches = bool((await conn.execute(_HAS_ROLE, {"role": APP_ROLE})).scalar())
            effective = APP_ROLE if switches else (await conn.execute(text("SELECT session_user"))).scalar()
            return bool((await conn.execute(_BYPASS, {"role": effective})).scalar())

    async def dispose(self) -> None:
        await self.engine.dispose()
