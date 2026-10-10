"""Checks of an asset and their lifecycle actions (spec 007, ADR-0005)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import Access
from ..auth.deps import actor_of
from ..db.models import CHECK_STATUSES, Asset, Check, CheckEvent
from ..deps import access, session
from ..logging import get_logger
from ..schemas import CheckActionIn, CheckEventOut, CheckOut
from ..services import audit
from ..services.checks import TRANSITIONS

router = APIRouter(prefix="/api/checks", tags=["checks"])
log = get_logger("sahifa.checks")

Action = Literal["approve", "reject", "lock", "unlock", "retire", "restore"]


def title_of(check_type: str) -> str:
    """The catalogue title of a check type; the type itself for one the catalogue lacks."""
    from sahifa_core.checks import BY_TYPE

    check = BY_TYPE.get(check_type)
    return check.title if check is not None else check_type


def to_out(c: Check) -> CheckOut:
    return CheckOut(
        id=c.id,
        key=c.key,
        type=c.type,
        title=title_of(c.type),
        column=c.column_name,
        columns=list(c.columns or []),
        params=dict(c.params or {}),
        dimension=c.dimension,
        severity=c.severity,
        kind=c.kind,
        origin=c.origin,
        status=c.status,
        max_fail_ratio=c.max_fail_ratio,
        version=c.version,
        updated_at=c.updated_at,
        last_scan_id=c.last_scan_id,
    )


@router.get("", response_model=list[CheckOut])
async def list_checks(
    asset_id: uuid.UUID,
    status: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> list[CheckOut]:
    if await db.get(Asset, asset_id) is None:
        raise HTTPException(404, "asset not found")
    stmt = select(Check).where(Check.asset_id == asset_id)
    if status:
        unknown = sorted(set(status) - set(CHECK_STATUSES))
        if unknown:
            raise HTTPException(422, f"status must be one of {', '.join(CHECK_STATUSES)}")
        stmt = stmt.where(Check.status.in_(status))
    stmt = stmt.order_by(Check.column_name.asc().nulls_first(), Check.type, Check.key)
    return [caller.stamp(to_out(c), c.workspace_id) for c in await db.scalars(stmt)]


@router.post("/{check_id}/{action}", response_model=CheckOut)
async def change_check(
    check_id: uuid.UUID,
    action: Action,
    body: CheckActionIn,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> CheckOut | JSONResponse:
    """One lifecycle action in one transaction: lock the row, compare versions, check the
    transition, change the status and record the event (behaviour 5)."""
    check = await db.scalar(select(Check).where(Check.id == check_id).with_for_update())
    if check is None:
        raise HTTPException(404, "check not found")
    caller.require(check.workspace_id, "editor", action=f"check.{action}")
    principal = caller.principal
    if check.version != body.version:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "stale_version",
                "version": check.version,
                "message": "Someone changed this check; reload it and try again.",
            },
        )
    source, target = TRANSITIONS[action]
    if check.status != source:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "invalid_transition",
                "status": check.status,
                "message": f"A {check.status} check cannot be changed with {action}.",
            },
        )
    version = check.version
    check.status = target
    check.version += 1
    check.updated_at = func.now()
    asset = await db.get(Asset, check.asset_id)
    label = asset.label if asset else ""
    audit.record(
        db,
        caller,
        action=f"check.{action}",
        workspace_id=check.workspace_id,
        object_type="check",
        object_id=check.id,
        summary=f"{audit.VERBS[action]} “{title_of(check.type)}” on "
        f"{audit.where(label, check.column_name or ', '.join(check.columns or []) or None)}",
        before={"status": source, "version": version},
        after={"status": target, "version": version + 1},
    )
    db.add(
        CheckEvent(
            check_id=check.id,
            user_id=principal.user_id,
            actor=actor_of(principal),
            action=action,
            from_status=source,
            to_status=target,
        )
    )
    await db.commit()
    await db.refresh(check)
    log.info(
        "check.changed",
        check_id=str(check.id),
        action=action,
        from_status=source,
        to_status=target,
        user_id=str(principal.user_id) if principal.user_id else None,
    )
    return caller.stamp(to_out(check), check.workspace_id)


@router.get("/{check_id}/events", response_model=list[CheckEventOut])
async def list_events(check_id: uuid.UUID, db: AsyncSession = Depends(session)) -> list[CheckEventOut]:
    if await db.get(Check, check_id) is None:
        raise HTTPException(404, "check not found")
    events = await db.scalars(
        select(CheckEvent)
        .where(CheckEvent.check_id == check_id)
        .order_by(CheckEvent.at.desc(), CheckEvent.id)
    )
    return [
        CheckEventOut(
            at=e.at,
            actor=e.actor,
            action=e.action,
            from_status=e.from_status,
            to_status=e.to_status,
            params_before=e.params_before,
            params_after=e.params_after,
        )
        for e in events
    ]
