"""Workspaces: moving a connection with everything that belongs to it (spec 016), and deleting a
workspace (spec 020)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, delete, exists, func, select, text, update
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
    Invitation,
    Membership,
    Scan,
    ScanSchedule,
    ScoreRecord,
    Workspace,
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


class HasConnectionsError(Exception):
    """The workspace holds connections from `SAHIFA_CONN_*`; they would come back in the default
    workspace at the next start, so they are moved first."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(names)
        self.names = names


@dataclass
class Deleted:
    """What a workspace deletion removed: counts for the audit entry, and the upload folders to
    remove from the data directory once the transaction has committed."""

    counts: dict[str, int]
    folders: list[Path] = field(default_factory=list)


async def delete_workspace(db: AsyncSession, ws: Workspace) -> Deleted:
    """Delete a workspace and everything in it, in the caller's transaction (spec 020)."""
    await db.execute(select(Workspace.id).where(Workspace.id == ws.id).with_for_update())
    conns = list(await db.scalars(select(Connection).where(Connection.workspace_id == ws.id)))
    registered = sorted(c.name for c in conns if c.kind != "upload")
    if registered:
        raise HasConnectionsError(registered)
    ids = [c.id for c in conns]
    running = await db.scalar(
        select(exists().where(Scan.connection_id.in_(ids), Scan.status.in_(ACTIVE_SCANS)))
    )
    if running:
        raise ScanRunningError

    async def count(model: type[Any], where: ColumnElement[bool]) -> int:
        return int(await db.scalar(select(func.count()).select_from(model).where(where)) or 0)

    counts = {
        "uploads": len(ids),
        "scans": await count(Scan, Scan.connection_id.in_(ids)),
        "findings": await count(Finding, Finding.workspace_id == ws.id),
        "members": await count(Membership, Membership.workspace_id == ws.id),
        "invitations": await count(Invitation, Invitation.workspace_id == ws.id),
    }
    folders = sorted({Path(p).parent for c in conns for p in (c.config or {}).get("paths", [])})
    # The audit entries of the workspace go with it (spec 018's purge setting, this transaction only).
    await db.execute(text("SELECT set_config('sahifa.audit_purge', 'on', true)"))
    # Connections cascade to scans, assets, checks, findings, events, schedules and scores;
    # the workspace then cascades to memberships, invitations and audit entries.
    await db.execute(delete(Connection).where(Connection.workspace_id == ws.id))
    await db.execute(delete(Workspace).where(Workspace.id == ws.id))
    return Deleted(counts=counts, folders=folders)
