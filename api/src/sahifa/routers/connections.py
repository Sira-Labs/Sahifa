"""Connections (spec 004): registered sources, never uploads, never credentials.

Each belongs to a workspace (spec 016); creating one needs the admin role there."""

from __future__ import annotations

import os
import uuid

import anyio
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import Access
from ..db.models import Connection, ScanSchedule
from ..deps import access, session, settings
from ..logging import get_logger
from ..schemas import ConnectionIn, ConnectionOut, ConnectionTest, Items, ScheduleSummary
from ..services import audit
from ..services.connections import list_visible, public_config, resolve
from ..settings import CONNECTION_PREFIX, Settings

router = APIRouter(prefix="/api/connections", tags=["connections"])
log = get_logger("sahifa.connections")


def to_out(conn: Connection, schedule: ScanSchedule | None = None) -> ConnectionOut:
    available = resolve(conn) is not None
    summary = (
        ScheduleSummary(
            cron=schedule.cron,
            timezone=schedule.timezone,
            enabled=schedule.enabled,
            next_run_at=schedule.next_run_at,
        )
        if schedule
        else None
    )
    return ConnectionOut(
        id=conn.id,
        name=conn.name,
        kind=conn.kind,
        config=public_config(conn),
        secret_ref=conn.secret_ref,
        available=available,
        created_at=conn.created_at,
        schedule=summary,
    )


async def schedules_of(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, ScanSchedule]:
    """The schedules of these connections (spec 010), by connection id."""
    if not ids:
        return {}
    rows = await db.scalars(select(ScanSchedule).where(ScanSchedule.connection_id.in_(ids)))
    return {s.connection_id: s for s in rows}


@router.get("", response_model=Items[ConnectionOut])
async def list_connections(
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> Items[ConnectionOut]:
    conns = await list_visible(db, workspace_id)
    schedules = await schedules_of(db, [c.id for c in conns])
    return Items[ConnectionOut](
        items=[caller.stamp(to_out(c, schedules.get(c.id)), c.workspace_id) for c in conns]
    )


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionIn, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> ConnectionOut:
    workspace_id = caller.pick(body.workspace_id, "admin", action="connection.create")
    if not body.secret_ref.startswith(CONNECTION_PREFIX):
        raise HTTPException(
            422, f"secret_ref must name an environment variable starting with {CONNECTION_PREFIX}"
        )
    if not os.environ.get(body.secret_ref, "").strip():
        raise HTTPException(422, f"{body.secret_ref} is not set on the server")
    conn = Connection(
        name=body.name,
        kind=body.kind,
        secret_ref=body.secret_ref,
        config=body.config,
        workspace_id=workspace_id,
        id=uuid.uuid4(),
    )
    db.add(conn)
    # The credential by its variable's name only; the config is not recorded (spec 018).
    audit.record(
        db,
        caller,
        action="connection.created",
        workspace_id=workspace_id,
        object_type="connection",
        object_id=conn.id,
        summary=f"Registered the connection {conn.name}",
        after={"name": conn.name, "kind": conn.kind, "secret_ref": conn.secret_ref},
    )
    try:
        await db.commit()
    except IntegrityError as e:
        raise HTTPException(409, f"a connection named {body.name!r} exists") from e
    await db.refresh(conn)
    return caller.stamp(to_out(conn), conn.workspace_id)


async def _get(db: AsyncSession, connection_id: uuid.UUID) -> Connection:
    conn = await db.get(Connection, connection_id)
    if conn is None or conn.kind == "upload":
        raise HTTPException(404, "connection not found")
    return conn


@router.get("/{connection_id}", response_model=ConnectionOut)
async def get_connection(
    connection_id: uuid.UUID, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> ConnectionOut:
    conn = await _get(db, connection_id)
    return caller.stamp(to_out(conn, (await schedules_of(db, [conn.id])).get(conn.id)), conn.workspace_id)


@router.post("/{connection_id}/test", response_model=ConnectionTest)
async def test_connection(
    connection_id: uuid.UUID, db: AsyncSession = Depends(session), cfg: Settings = Depends(settings)
) -> ConnectionTest:
    conn = await _get(db, connection_id)
    source = resolve(conn)
    if source is None:
        return ConnectionTest(ok=False, assets=0, error=f"{conn.secret_ref} is not set on the server")

    def probe() -> int:
        from sahifa_core.connectors import open_source

        with open_source(
            source, statement_timeout_s=cfg.statement_timeout_s, application_name="sahifa/test"
        ) as src:
            return len(src.list_assets())

    try:
        count = await anyio.to_thread.run_sync(probe)
    except Exception as e:
        log.warning("conn.failed", connection=conn.name, error=str(e)[:300])
        return ConnectionTest(ok=False, assets=0, error=str(e)[:500])
    return ConnectionTest(ok=True, assets=count)
