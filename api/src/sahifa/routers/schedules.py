"""A connection's scan schedule (spec 010): read, create or replace, delete."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import Access
from ..auth.deps import actor_of
from ..db.models import Connection, ScanSchedule
from ..deps import access, session, settings
from ..logging import get_logger
from ..schemas import ScheduleIn, ScheduleOut
from ..services import audit
from ..services.schedules import ScheduleError, next_run, upcoming, validate
from ..settings import Settings

router = APIRouter(prefix="/api/connections", tags=["schedules"])
log = get_logger("sahifa.schedules")

NO_SCHEDULE = {"detail": "no_schedule", "message": "This connection has no schedule."}


def to_out(s: ScanSchedule) -> ScheduleOut:
    return ScheduleOut(
        cron=s.cron,
        timezone=s.timezone,
        enabled=s.enabled,
        sample_rows=s.sample_rows,
        next_run_at=s.next_run_at,
        next_runs=upcoming(s.cron, s.timezone, s.next_run_at if s.enabled else None),
        last_run_at=s.last_run_at,
        last_scan_id=s.last_scan_id,
        last_outcome=s.last_outcome,
        version=s.version,
        updated_at=s.updated_at,
        updated_by=s.updated_by,
    )


def _fields(s: ScanSchedule) -> dict[str, Any]:
    """What the audit log records of a schedule (spec 018)."""
    return {"cron": s.cron, "timezone": s.timezone, "enabled": s.enabled, "sample_rows": s.sample_rows}


def stale(version: int | None) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": "stale_version",
            "version": version,
            "message": "Someone changed this schedule; reload it and try again.",
        },
    )


async def _connection(db: AsyncSession, connection_id: uuid.UUID) -> Connection:
    conn = await db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(404, "connection not found")
    return conn


async def _schedule(db: AsyncSession, connection_id: uuid.UUID, *, lock: bool = False) -> ScanSchedule | None:
    stmt = select(ScanSchedule).where(ScanSchedule.connection_id == connection_id)
    return await db.scalar(stmt.with_for_update() if lock else stmt)


@router.get("/{connection_id}/schedule", response_model=ScheduleOut)
async def get_schedule(
    connection_id: uuid.UUID, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> ScheduleOut | JSONResponse:
    await _connection(db, connection_id)
    schedule = await _schedule(db, connection_id)
    if schedule is None:
        return JSONResponse(status_code=404, content=NO_SCHEDULE)
    return caller.stamp(to_out(schedule), schedule.workspace_id)


@router.put("/{connection_id}/schedule", response_model=ScheduleOut)
async def put_schedule(
    connection_id: uuid.UUID,
    body: ScheduleIn,
    db: AsyncSession = Depends(session),
    cfg: Settings = Depends(settings),
    caller: Access = Depends(access),
) -> ScheduleOut | JSONResponse:
    """Create or replace the schedule in one transaction: validate, lock the row, compare
    versions, store it with `next_run_at` computed from now (null while disabled)."""
    conn = await _connection(db, connection_id)
    caller.require(conn.workspace_id, "editor", action="schedule.save")
    if conn.kind == "upload":
        error = ScheduleError(
            "upload_connection",
            None,
            "Uploaded files cannot be scheduled; register the source as a connection instead.",
        )
        return JSONResponse(status_code=422, content=error.body())
    now = datetime.now(UTC)
    try:
        cron = validate(
            body.cron, body.timezone, min_interval_minutes=cfg.schedule_min_interval_minutes, now=now
        )
    except ScheduleError as e:
        return JSONResponse(status_code=422, content=e.body())
    schedule = await _schedule(db, connection_id, lock=True)
    current = schedule.version if schedule else None
    if body.version != current:
        return stale(current)
    actor = actor_of(caller.principal)
    before = _fields(schedule) if schedule else None
    if schedule is None:
        schedule = ScanSchedule(id=uuid.uuid4(), connection_id=connection_id, version=1)
        db.add(schedule)
    else:
        schedule.version += 1
        schedule.updated_at = func.now()
    schedule.cron, schedule.timezone, schedule.enabled = cron, body.timezone, body.enabled
    schedule.sample_rows = body.sample_rows
    schedule.next_run_at = next_run(cron, body.timezone, now) if body.enabled else None
    schedule.updated_by = actor
    was, now_ = audit.changed(before, _fields(schedule))
    audit.record(
        db,
        caller,
        action="schedule.saved",
        workspace_id=conn.workspace_id,
        object_type="schedule",
        object_id=schedule.id,
        summary=f"{'Changed' if before else 'Created'} the schedule of {conn.name}",
        before=was,
        after=now_,
    )
    try:
        await db.commit()
    except IntegrityError:  # created by a concurrent request
        await db.rollback()
        existing = await _schedule(db, connection_id)
        return stale(existing.version if existing else None)
    await db.refresh(schedule)
    log.info(
        "schedule.saved",
        connection_id=str(connection_id),
        cron=cron,
        timezone=body.timezone,
        enabled=body.enabled,
        actor=actor,
    )
    return caller.stamp(to_out(schedule), schedule.workspace_id)


@router.delete("/{connection_id}/schedule", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_schedule(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> Response:
    conn = await _connection(db, connection_id)
    caller.require(conn.workspace_id, "editor", action="schedule.delete")
    schedule = await _schedule(db, connection_id, lock=True)
    if schedule is None:
        return JSONResponse(status_code=404, content=NO_SCHEDULE)
    audit.record(
        db,
        caller,
        action="schedule.deleted",
        workspace_id=conn.workspace_id,
        object_type="schedule",
        object_id=schedule.id,
        summary=f"Removed the schedule of {conn.name}",
        before=_fields(schedule),
    )
    await db.delete(schedule)
    await db.commit()
    log.info("schedule.deleted", connection_id=str(connection_id), actor=actor_of(caller.principal))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
