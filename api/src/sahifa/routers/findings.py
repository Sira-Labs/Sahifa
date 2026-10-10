"""Findings across scans and the status people give them (spec 009)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ..auth.access import Access
from ..db.models import FINDING_STATUSES, Asset, Check, Finding, FindingEvent, FindingOccurrence, Scan
from ..deps import access, session
from ..logging import get_logger
from ..schemas import (
    FindingActionIn,
    FindingAsset,
    FindingCheck,
    FindingDetail,
    FindingEventOut,
    FindingLatest,
    FindingOut,
    OccurrenceOut,
    Page,
)
from ..services.findings import SEVERITIES, TRANSITIONS
from .checks import actor_of, title_of

router = APIRouter(prefix="/api/findings", tags=["findings"])
log = get_logger("sahifa.findings")

Action = Literal["acknowledge", "resolve", "mute", "unmute", "reopen"]
DEFAULT_STATUSES = ("open", "acknowledged", "muted")
OCCURRENCES_SHOWN = 20
Row = tuple[Finding, Check, Asset]


def _rank() -> ColumnElement[int]:
    """Severity as a number for ordering: critical first, an unknown severity last."""
    return case({s: i for i, s in enumerate(SEVERITIES)}, value=Finding.severity, else_=len(SEVERITIES))


def _cursor(f: Finding) -> str:
    rank = SEVERITIES.index(f.severity) if f.severity in SEVERITIES else len(SEVERITIES)
    raw = json.dumps([rank, f.last_seen_at.isoformat(), str(f.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _after(cursor: str) -> tuple[int, datetime, uuid.UUID]:
    try:
        rank, seen, fid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return int(rank), datetime.fromisoformat(seen), uuid.UUID(fid)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, "invalid cursor") from e


def _column(c: Check) -> str | None:
    """The check's column, or its columns joined as the core names them in a finding."""
    return c.column_name or (", ".join(c.columns or []) or None)


def _out(f: Finding, c: Check, a: Asset, latest: FindingOccurrence | None) -> FindingOut:
    return FindingOut(
        id=f.id,
        status=f.status,
        severity=f.severity,
        occurrences=f.occurrences,
        first_seen_at=f.first_seen_at,
        last_seen_at=f.last_seen_at,
        muted_until=f.muted_until,
        version=f.version,
        check=FindingCheck(
            id=c.id, key=c.key, type=c.type, title=title_of(c.type), status=c.status, column=_column(c)
        ),
        asset=FindingAsset(id=a.id, label=a.label, connection_id=a.connection_id),
        latest=None
        if latest is None
        else FindingLatest(
            scan_id=latest.scan_id,
            summary=latest.summary,
            failed=latest.failed,
            evaluated=latest.evaluated,
            ratio=latest.ratio,
            low=latest.low,
            high=latest.high,
            dimension=latest.dimension,
        ),
    )


async def _items(db: AsyncSession, rows: list[Row]) -> list[FindingOut]:
    """The findings with their most recent occurrence each, in one query."""
    ids = [f.id for f, _, _ in rows]
    latest: dict[uuid.UUID, FindingOccurrence] = {}
    if ids:
        newest = (
            func.row_number()
            .over(
                partition_by=FindingOccurrence.finding_id,
                order_by=(Scan.created_at.desc(), FindingOccurrence.id),
            )
            .label("n")
        )
        ranked = (
            select(FindingOccurrence.id, newest)
            .join(Scan, Scan.id == FindingOccurrence.scan_id)
            .where(FindingOccurrence.finding_id.in_(ids))
            .subquery()
        )
        occurrences = await db.scalars(
            select(FindingOccurrence).join(ranked, ranked.c.id == FindingOccurrence.id).where(ranked.c.n == 1)
        )
        latest = {o.finding_id: o for o in occurrences if o.finding_id is not None}
    return [_out(f, c, a, latest.get(f.id)) for f, c, a in rows]


def _joined() -> Any:
    return (
        select(Finding, Check, Asset)
        .join(Check, Check.id == Finding.check_id)
        .join(Asset, Asset.id == Check.asset_id)
    )


async def _row(db: AsyncSession, finding_id: uuid.UUID) -> Row:
    row = (await db.execute(_joined().where(Finding.id == finding_id))).first()
    if row is None:
        raise HTTPException(404, "finding not found")
    return row[0], row[1], row[2]


@router.get("", response_model=Page[FindingOut])
async def list_findings(
    connection_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    status: list[str] | None = Query(default=None),
    severity: list[str] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> Page[FindingOut]:
    statuses = status or list(DEFAULT_STATUSES)
    if set(statuses) - set(FINDING_STATUSES):
        raise HTTPException(422, f"status must be one of {', '.join(FINDING_STATUSES)}")
    stmt = _joined().where(Finding.status.in_(statuses))
    if severity:
        if set(severity) - set(SEVERITIES):
            raise HTTPException(422, f"severity must be one of {', '.join(SEVERITIES)}")
        stmt = stmt.where(Finding.severity.in_(severity))
    if connection_id is not None:
        stmt = stmt.where(Asset.connection_id == connection_id)
    if asset_id is not None:
        stmt = stmt.where(Check.asset_id == asset_id)
    if workspace_id is not None:
        stmt = stmt.where(Finding.workspace_id == workspace_id)
    rank = _rank()
    if cursor:
        after, seen, fid = _after(cursor)
        stmt = stmt.where(
            or_(
                rank > after,
                and_(
                    rank == after,
                    or_(
                        Finding.last_seen_at < seen,
                        and_(Finding.last_seen_at == seen, Finding.id > fid),
                    ),
                ),
            )
        )
    stmt = stmt.order_by(rank, Finding.last_seen_at.desc(), Finding.id).limit(limit + 1)
    rows: list[Row] = [(r[0], r[1], r[2]) for r in (await db.execute(stmt)).all()]
    nxt = _cursor(rows[limit - 1][0]) if len(rows) > limit else None
    items = await _items(db, rows[:limit])
    return Page[FindingOut](
        items=[caller.stamp(item, f.workspace_id) for item, (f, _, _) in zip(items, rows, strict=False)],
        next_cursor=nxt,
    )


@router.get("/{finding_id}", response_model=FindingDetail)
async def get_finding(
    finding_id: uuid.UUID, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> FindingDetail:
    row = await _row(db, finding_id)
    item = caller.stamp((await _items(db, [row]))[0], row[0].workspace_id)
    occurrences = (
        await db.execute(
            select(FindingOccurrence, Scan)
            .join(Scan, Scan.id == FindingOccurrence.scan_id)
            .where(FindingOccurrence.finding_id == finding_id)
            .order_by(Scan.created_at.desc(), FindingOccurrence.id)
            .limit(OCCURRENCES_SHOWN)
        )
    ).all()
    events = await db.scalars(
        select(FindingEvent)
        .where(FindingEvent.finding_id == finding_id)
        .order_by(FindingEvent.at.desc(), FindingEvent.id)
    )
    return FindingDetail(
        **item.model_dump(),
        occurrences_list=[
            OccurrenceOut(
                scan_id=o.scan_id,
                at=s.finished_at or s.created_at,
                failed=o.failed,
                evaluated=o.evaluated,
                ratio=o.ratio,
                low=o.low,
                high=o.high,
                summary=o.summary,
                examples=list(o.evidence.get("examples", [])),
                sql=o.evidence.get("sql"),
                next_step=o.next_step,
            )
            for o, s in occurrences
        ],
        events=[
            FindingEventOut(
                at=e.at,
                actor=e.actor,
                action=e.action,
                from_status=e.from_status,
                to_status=e.to_status,
                note=e.note,
            )
            for e in events
        ],
    )


@router.post("/{finding_id}/{action}", response_model=FindingOut)
async def change_finding(
    finding_id: uuid.UUID,
    action: Action,
    body: FindingActionIn,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> FindingOut | JSONResponse:
    """One status change in one transaction: lock the row, compare versions, check the
    transition, change the status and record the event with the note (behaviour 4)."""
    until = body.until
    if until is not None:
        if action != "mute":
            raise HTTPException(422, "until is only allowed with mute")
        until = until if until.tzinfo else until.replace(tzinfo=UTC)
        if until <= datetime.now(UTC):
            raise HTTPException(422, "until must be in the future")
    finding = await db.scalar(select(Finding).where(Finding.id == finding_id).with_for_update())
    if finding is None:
        raise HTTPException(404, "finding not found")
    caller.require(finding.workspace_id, "editor", action=f"finding.{action}")
    principal = caller.principal
    if finding.version != body.version:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "stale_version",
                "version": finding.version,
                "message": "Someone changed this finding; reload it and try again.",
            },
        )
    sources, target = TRANSITIONS[action]
    source = finding.status
    if source not in sources:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "invalid_transition",
                "status": source,
                "message": f"A {source} finding cannot be changed with {action}.",
            },
        )
    finding.status = target
    # `muted_until` only means something while muted: mute sets it (null: indefinitely),
    # every other change clears it.
    finding.muted_until = until if action == "mute" else None
    if action == "resolve":
        finding.resolved_at, finding.resolved_scan_id = func.now(), None
    elif action == "reopen":
        finding.resolved_at = finding.resolved_scan_id = None
    finding.version += 1
    finding.updated_at = func.now()
    note = body.note if body.note and body.note.strip() else None
    db.add(
        FindingEvent(
            finding_id=finding.id,
            user_id=principal.user_id,
            actor=actor_of(principal),
            action=action,
            from_status=source,
            to_status=target,
            note=note,
        )
    )
    await db.commit()
    log.info(
        "finding.changed",
        finding_id=str(finding.id),
        action=action,
        from_status=source,
        to_status=target,
        user_id=str(principal.user_id) if principal.user_id else None,
    )
    row = await _row(db, finding_id)
    await db.refresh(row[0])
    return caller.stamp((await _items(db, [row]))[0], row[0].workspace_id)
