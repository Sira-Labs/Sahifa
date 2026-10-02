"""Connections (spec 004): registered sources, never uploads, never credentials."""

from __future__ import annotations

import os
import uuid

import anyio
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Connection
from ..deps import session, settings
from ..logging import get_logger
from ..schemas import ConnectionIn, ConnectionOut, ConnectionTest, Items
from ..services.connections import list_visible, public_config, resolve
from ..settings import CONNECTION_PREFIX, Settings

router = APIRouter(prefix="/api/connections", tags=["connections"])
log = get_logger("sahifa.connections")


def to_out(conn: Connection) -> ConnectionOut:
    available = resolve(conn) is not None
    return ConnectionOut(id=conn.id, name=conn.name, kind=conn.kind, config=public_config(conn),
                         secret_ref=conn.secret_ref, available=available, created_at=conn.created_at)


@router.get("", response_model=Items[ConnectionOut])
async def list_connections(db: AsyncSession = Depends(session)) -> Items[ConnectionOut]:
    return Items[ConnectionOut](items=[to_out(c) for c in await list_visible(db)])


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_connection(body: ConnectionIn, db: AsyncSession = Depends(session)) -> ConnectionOut:
    if not body.secret_ref.startswith(CONNECTION_PREFIX):
        raise HTTPException(422, f"secret_ref must name an environment variable starting with {CONNECTION_PREFIX}")
    if not os.environ.get(body.secret_ref, "").strip():
        raise HTTPException(422, f"{body.secret_ref} is not set on the server")
    conn = Connection(name=body.name, kind=body.kind, secret_ref=body.secret_ref, config=body.config)
    db.add(conn)
    try:
        await db.commit()
    except IntegrityError as e:
        raise HTTPException(409, f"a connection named {body.name!r} exists") from e
    await db.refresh(conn)
    return to_out(conn)


async def _get(db: AsyncSession, connection_id: uuid.UUID) -> Connection:
    conn = await db.get(Connection, connection_id)
    if conn is None or conn.kind == "upload":
        raise HTTPException(404, "connection not found")
    return conn


@router.get("/{connection_id}", response_model=ConnectionOut)
async def get_connection(connection_id: uuid.UUID, db: AsyncSession = Depends(session)) -> ConnectionOut:
    return to_out(await _get(db, connection_id))


@router.post("/{connection_id}/test", response_model=ConnectionTest)
async def test_connection(connection_id: uuid.UUID, db: AsyncSession = Depends(session),
                          cfg: Settings = Depends(settings)) -> ConnectionTest:
    conn = await _get(db, connection_id)
    source = resolve(conn)
    if source is None:
        return ConnectionTest(ok=False, assets=0, error=f"{conn.secret_ref} is not set on the server")

    def probe() -> int:
        from sahifa_core.connectors import open_source

        with open_source(source, statement_timeout_s=cfg.statement_timeout_s,
                         application_name="sahifa/test") as src:
            return len(src.list_assets())

    try:
        count = await anyio.to_thread.run_sync(probe)
    except Exception as e:  # noqa: BLE001 - the message goes back to the person testing
        log.warning("conn.failed", connection=conn.name, error=str(e)[:300])
        return ConnectionTest(ok=False, assets=0, error=str(e)[:500])
    return ConnectionTest(ok=True, assets=count)
