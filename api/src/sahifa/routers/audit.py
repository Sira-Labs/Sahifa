"""The audit log, read-only (spec 018): workspace admins read their workspaces' entries, the org
admin all of them."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import Access
from ..db.models import AuditEvent
from ..deps import access, session
from ..schemas import AuditEntry, Page, WorkspaceRef

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _cursor(e: AuditEvent) -> str:
    raw = json.dumps([e.at.isoformat(), str(e.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _after(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        at, eid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(at), uuid.UUID(eid)
    # ValueError covers bad base64 (binascii.Error) and JSON; AttributeError a non-string id.
    except (ValueError, TypeError, AttributeError) as e:
        raise HTTPException(422, "invalid cursor") from e


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("", response_model=Page[AuditEntry])
async def list_audit(
    workspace_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=40),
    actor: str | None = Query(default=None, max_length=200),
    object_type: str | None = Query(default=None, max_length=20),
    object_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> Page[AuditEntry]:
    """Newest first. `action` is an exact action or a prefix ending in a dot (`check.`)."""
    caller.require_any("admin", action="audit.read")
    # Row-level security limits the rows to the caller's workspaces; only those they administer
    # are theirs to read here.
    readable = [w for w in caller.workspaces if caller.allows(w, "admin")]
    stmt = select(AuditEvent).where(AuditEvent.workspace_id.in_(readable))
    if workspace_id is not None:
        stmt = stmt.where(AuditEvent.workspace_id == workspace_id)
    if action:
        stmt = stmt.where(
            AuditEvent.action.startswith(action, autoescape=True)
            if action.endswith(".")
            else AuditEvent.action == action
        )
    if actor:
        stmt = stmt.where(AuditEvent.actor.ilike(_like(actor), escape="\\"))
    if object_type:
        stmt = stmt.where(AuditEvent.object_type == object_type)
    if object_id is not None:
        stmt = stmt.where(AuditEvent.object_id == object_id)
    if since is not None:
        stmt = stmt.where(AuditEvent.at >= since)
    if until is not None:
        stmt = stmt.where(AuditEvent.at < until)
    if cursor:
        at, eid = _after(cursor)
        stmt = stmt.where(or_(AuditEvent.at < at, and_(AuditEvent.at == at, AuditEvent.id < eid)))
    rows = list(await db.scalars(stmt.order_by(AuditEvent.at.desc(), AuditEvent.id.desc()).limit(limit + 1)))
    items = [
        AuditEntry(
            id=e.id,
            at=e.at,
            workspace=WorkspaceRef(id=e.workspace_id, name=caller.name_of(e.workspace_id) or ""),
            actor=e.actor,
            action=e.action,
            object_type=e.object_type,
            object_id=e.object_id,
            summary=e.summary,
            before=e.before,
            after=e.after,
        )
        for e in rows[:limit]
    ]
    return Page[AuditEntry](items=items, next_cursor=_cursor(rows[limit - 1]) if len(rows) > limit else None)
