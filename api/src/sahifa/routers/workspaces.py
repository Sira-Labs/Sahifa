"""Workspaces, members and moving connections (spec 016).

Workspaces and memberships are not under row-level security; these routes decide from the
caller's access who sees and changes what: a workspace the caller is not in gives 404, a role
too low gives 403 `forbidden_role`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import Access
from ..db.models import Connection, Membership, Organisation, User, Workspace
from ..deps import access, session
from ..logging import get_logger
from ..schemas import ConnectionOut, MemberIn, MemberOut, MoveIn, UserMatch, WorkspaceIn, WorkspaceOut
from ..services.workspaces import ScanRunningError, move_connection
from .connections import to_out as connection_out

router = APIRouter(prefix="/api", tags=["workspaces"])
log = get_logger("sahifa.workspaces")

USERS_SHOWN = 20
NAME_TAKEN = {"detail": "name_taken", "message": "A workspace with this name exists."}
OWN_MEMBERSHIP = {
    "detail": "own_membership",
    "message": "You cannot lower or remove your own admin role; ask another admin.",
}


def _actor(caller: Access) -> str | None:
    return str(caller.principal.user_id) if caller.principal.user_id else caller.principal.mode


def _visible(caller: Access, workspace_id: uuid.UUID) -> None:
    if workspace_id not in caller.workspaces:
        raise HTTPException(404, "workspace not found")


async def _sizes(db: AsyncSession, ids: list[uuid.UUID]) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    """Registered connections (as the session sees them) and members per workspace."""
    conns = await db.execute(
        select(Connection.workspace_id, func.count())
        .where(Connection.workspace_id.in_(ids), Connection.kind != "upload")
        .group_by(Connection.workspace_id)
    )
    members = await db.execute(
        select(Membership.workspace_id, func.count())
        .where(Membership.workspace_id.in_(ids))
        .group_by(Membership.workspace_id)
    )
    return {w: int(n) for w, n in conns.all()}, {w: int(n) for w, n in members.all()}


async def _out(db: AsyncSession, caller: Access, ws: Workspace, role: str | None = None) -> WorkspaceOut:
    conns, members = await _sizes(db, [ws.id])
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        role=role or caller.role_in(ws.id) or "admin",
        is_default=ws.is_default,
        connections=conns.get(ws.id, 0),
        members=members.get(ws.id, 0),
        created_at=ws.created_at,
    )


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> list[WorkspaceOut]:
    """The caller's workspaces with their role; every workspace for the org admin."""
    ids = list(caller.workspaces)
    rows = list(await db.scalars(select(Workspace).where(Workspace.id.in_(ids)).order_by(Workspace.name)))
    conns, members = await _sizes(db, ids)
    return [
        WorkspaceOut(
            id=w.id,
            name=w.name,
            role=caller.role_in(w.id) or "viewer",
            is_default=w.is_default,
            connections=conns.get(w.id, 0),
            members=members.get(w.id, 0),
            created_at=w.created_at,
        )
        for w in rows
    ]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceIn, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> WorkspaceOut | JSONResponse:
    caller.require_org_admin(action="workspace.create")
    org = await db.scalar(select(Organisation.id).limit(1))
    ws = Workspace(organisation_id=org, name=body.name.strip())
    db.add(ws)
    try:
        await db.commit()
    except IntegrityError:
        return JSONResponse(status_code=409, content=NAME_TAKEN)
    await db.refresh(ws)
    log.info("workspace.created", workspace_id=str(ws.id), name=ws.name, actor=_actor(caller))
    return await _out(db, caller, ws, role="admin")


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def rename_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceIn,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> WorkspaceOut | JSONResponse:
    _visible(caller, workspace_id)
    caller.require(workspace_id, "admin", action="workspace.rename")
    ws = await db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "workspace not found")
    before, ws.name = ws.name, body.name.strip()
    try:
        await db.commit()
    except IntegrityError:
        return JSONResponse(status_code=409, content=NAME_TAKEN)
    log.info("workspace.renamed", workspace_id=str(ws.id), before=before, name=ws.name, actor=_actor(caller))
    return await _out(db, caller, ws)


def _member_out(user: User, role: str) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=role,
        last_login_at=user.last_login_at,
    )


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> list[MemberOut]:
    _visible(caller, workspace_id)
    caller.require(workspace_id, "admin", action="members.list")
    rows = await db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(User.email)
    )
    return [_member_out(u, role) for u, role in rows.all()]


def _own(caller: Access, user_id: uuid.UUID) -> bool:
    """A workspace admin changing their own membership; the org admin may."""
    return not caller.org_admin and caller.principal.user_id == user_id


@router.put("/workspaces/{workspace_id}/members/{user_id}", response_model=MemberOut)
async def put_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberIn,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> MemberOut | JSONResponse:
    """Add a person who has signed in, or change their role."""
    _visible(caller, workspace_id)
    caller.require(workspace_id, "admin", action="members.change")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found; they need to sign in once first")
    if _own(caller, user_id) and body.role != "admin":
        return JSONResponse(status_code=409, content=OWN_MEMBERSHIP)
    member = await db.get(Membership, (workspace_id, user_id), with_for_update=True)
    before = member.role if member else None
    if member is None:
        member = Membership(
            workspace_id=workspace_id, user_id=user_id, role=body.role, created_by=caller.principal.user_id
        )
        db.add(member)
    else:
        member.role = body.role
    await db.commit()
    log.info(
        "membership.changed",
        workspace_id=str(workspace_id),
        user_id=str(user_id),
        before=before,
        role=body.role,
        actor=_actor(caller),
    )
    return _member_out(user, body.role)


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> Response:
    _visible(caller, workspace_id)
    caller.require(workspace_id, "admin", action="members.remove")
    if _own(caller, user_id):
        return JSONResponse(status_code=409, content=OWN_MEMBERSHIP)
    member = await db.get(Membership, (workspace_id, user_id))
    if member is None:
        raise HTTPException(404, "not a member")
    before = member.role
    await db.delete(member)
    await db.commit()
    log.info(
        "membership.changed",
        workspace_id=str(workspace_id),
        user_id=str(user_id),
        before=before,
        role=None,
        actor=_actor(caller),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _like(q: str) -> str:
    """A LIKE pattern for `q` as a substring, its wildcards taken literally."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/users", response_model=list[UserMatch])
async def search_users(
    q: str = Query(min_length=1, max_length=200),
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> list[UserMatch]:
    """People who have signed in, by email or name, to add as members (workspace admins)."""
    caller.require_any("admin", action="users.search")
    pattern = _like(q.strip())
    rows = await db.scalars(
        select(User)
        .where(or_(User.email.ilike(pattern, escape="\\"), User.display_name.ilike(pattern, escape="\\")))
        .order_by(User.email)
        .limit(USERS_SHOWN)
    )
    return [UserMatch(id=u.id, email=u.email, display_name=u.display_name) for u in rows]


@router.put("/connections/{connection_id}/workspace", response_model=ConnectionOut)
async def move(
    connection_id: uuid.UUID,
    body: MoveIn,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> ConnectionOut | JSONResponse:
    """Move a connection with its scans, assets, checks, findings, schedule and scores to
    another workspace, in one transaction (org admin)."""
    caller.require_org_admin(action="connection.move")
    conn = await db.get(Connection, connection_id)
    if conn is None or conn.kind == "upload":
        raise HTTPException(404, "connection not found")
    if await db.get(Workspace, body.workspace_id) is None:
        raise HTTPException(404, "workspace not found")
    before = conn.workspace_id
    try:
        rows = await move_connection(db, conn, body.workspace_id)
    except ScanRunningError:
        await db.rollback()
        return JSONResponse(
            status_code=409,
            content={
                "detail": "scan_running",
                "message": "A scan of this connection is queued or running; move it once the scan is done.",
            },
        )
    await db.commit()
    log.info(
        "connection.moved",
        connection_id=str(conn.id),
        before=str(before),
        workspace_id=str(body.workspace_id),
        rows=rows,
        actor=_actor(caller),
    )
    return caller.stamp(connection_out(conn), conn.workspace_id)
