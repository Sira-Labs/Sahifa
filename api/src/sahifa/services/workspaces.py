"""Workspaces (spec 016): moving a connection with everything that belongs to it."""

from __future__ import annotations

import uuid

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    Asset,
    AssetColumn,
    Check,
    CheckEvent,
    Connection,
    Finding,
    FindingEvent,
    FindingOccurrence,
    Scan,
    ScanSchedule,
    ScoreRecord,
)

ACTIVE_SCANS = ("queued", "running")


class ScanRunningError(Exception):
    """The connection has a scan queued or running; its rows are still being written."""


async def move_connection(db: AsyncSession, conn: Connection, workspace_id: uuid.UUID) -> int:
    """Give the connection and every row under it the workspace, in the caller's transaction.
    Locks the connection first; returns the number of rows changed besides the connection."""
    await db.execute(select(Connection.id).where(Connection.id == conn.id).with_for_update())
    running = await db.scalar(
        select(exists().where(Scan.connection_id == conn.id, Scan.status.in_(ACTIVE_SCANS)))
    )
    if running:
        raise ScanRunningError
    assets = select(Asset.id).where(Asset.connection_id == conn.id).scalar_subquery()
    checks = select(Check.id).where(Check.asset_id.in_(assets)).scalar_subquery()
    findings = select(Finding.id).where(Finding.check_id.in_(checks)).scalar_subquery()
    scans = select(Scan.id).where(Scan.connection_id == conn.id).scalar_subquery()
    # Leaves first, so each subquery still finds its parents by their old rows.
    targets = (
        (FindingEvent, FindingEvent.finding_id.in_(findings)),
        (CheckEvent, CheckEvent.check_id.in_(checks)),
        (FindingOccurrence, FindingOccurrence.scan_id.in_(scans)),
        (Finding, Finding.check_id.in_(checks)),
        (AssetColumn, AssetColumn.asset_id.in_(assets)),
        (Check, Check.asset_id.in_(assets)),
        (ScoreRecord, ScoreRecord.connection_id == conn.id),
        (ScanSchedule, ScanSchedule.connection_id == conn.id),
        (Asset, Asset.connection_id == conn.id),
        (Scan, Scan.connection_id == conn.id),
    )
    moved = 0
    for model, where in targets:
        result = await db.execute(
            update(model)
            .where(where)
            .values(workspace_id=workspace_id)
            .execution_options(synchronize_session=False)
        )
        moved += result.rowcount or 0  # type: ignore[attr-defined]
    conn.workspace_id = workspace_id
    return moved
