"""Connections: registration from `SAHIFA_CONN_*` and resolution of their credentials."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Connection
from ..logging import get_logger
from ..settings import CONNECTION_PREFIX, connection_env

log = get_logger("sahifa.connections")


def kind_of(url: str) -> str:
    return "postgres" if url.startswith(("postgres://", "postgresql://")) else "duckdb"


def resolve(conn: Connection) -> str | list[str] | None:
    """The source string the core opens: an env URL for registered sources, file paths for uploads."""
    if conn.kind == "upload":
        files = conn.config.get("paths", [])
        return list(files) if files else None
    if not conn.secret_ref:
        return None
    value = os.environ.get(conn.secret_ref, "").strip()
    return value or None


async def register_from_env(db: AsyncSession) -> int:
    """Upsert one connection per `SAHIFA_CONN_<NAME>`; the name is `<name>` in lower case."""
    count = 0
    for var, url in connection_env().items():
        name = var.removeprefix(CONNECTION_PREFIX).lower().replace("_", "-")
        stmt = insert(Connection).values(name=name, kind=kind_of(url), secret_ref=var, config={})
        stmt = stmt.on_conflict_do_update(index_elements=["name"],
                                          set_={"kind": kind_of(url), "secret_ref": var})
        await db.execute(stmt)
        count += 1
    await db.commit()
    if count:
        log.info("conn.registered", count=count)
    return count


async def list_visible(db: AsyncSession) -> list[Connection]:
    rows = await db.scalars(select(Connection).where(Connection.kind != "upload").order_by(Connection.name))
    return list(rows)


def public_config(conn: Connection) -> dict[str, Any]:
    """Config without file paths of uploads (they reveal the server's layout)."""
    return {k: v for k, v in conn.config.items() if k != "paths"}
