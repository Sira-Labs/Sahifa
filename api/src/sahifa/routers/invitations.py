"""Invitations by link (spec 020).

`router` holds the admins' routes and acts for a person with workspace access. `token_router`
holds looking up and accepting a link: they need only a signed-in session, because the person
accepting has no workspace yet, and they read the invitation as the system (the token is the
proof). Neither the token nor the link is ever logged or recorded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import Access
from ..auth.deps import Principal, signed_in
from ..db import Database
from ..db.models import Invitation, User, Workspace
from ..deps import access, session, settings
from ..logging import get_logger
from ..schemas import (
    InvitationAccepted,
    InvitationCreated,
    InvitationIn,
    InvitationLookup,
    InvitationOut,
    TokenIn,
    WorkspaceRef,
)
from ..services import audit
from ..services import invitations as inv
from ..settings import Settings

router = APIRouter(prefix="/api", tags=["invitations"])
token_router = APIRouter(prefix="/api/invitations", tags=["invitations"])
log = get_logger("sahifa.invitations")

LISTED = 50
INVALID = {
    "detail": "invitation_invalid",
    "message": "This invitation link is not valid: it may have expired or been revoked. Ask for a new one.",
}
USED = {"detail": "invitation_used", "message": "This invitation has been used already."}
NEEDS_SIGN_IN = {
    "detail": "sign_in_required",
    "message": "Invitations need sign-in (SAHIFA_AUTH_MODE=oidc); this install has no personal accounts.",
}


def _out(row: Invitation) -> InvitationOut:
    return InvitationOut(
        id=row.id,
        workspace_id=row.workspace_id,
        email=row.email,
        role=row.role,
        created_at=row.created_at,
        expires_at=row.expires_at,
        status=inv.status_of(row),
        accepted_at=row.accepted_at,
    )


def _visible(caller: Access, workspace_id: uuid.UUID) -> None:
    if workspace_id not in caller.workspaces:
        raise HTTPException(404, "workspace not found")


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    workspace_id: uuid.UUID,
    body: InvitationIn,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
    cfg: Settings = Depends(settings),
) -> InvitationCreated | JSONResponse:
    """Invite an address with a role; the answer carries the link, the only time it is shown."""
    _visible(caller, workspace_id)
    caller.require(workspace_id, "admin", action="invitation.create")
    if cfg.resolved_auth_mode != "oidc":
        return JSONResponse(status_code=409, content=NEEDS_SIGN_IN)
    try:
        row, token = await inv.create(
            db,
            workspace_id=workspace_id,
            email=body.email,
            role=body.role,
            created_by=caller.principal.user_id,
            ttl_days=cfg.invitation_ttl_days,
        )
    except inv.AlreadyMemberError as e:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "already_member",
                "role": e.role,
                "message": f"This person is already a member as {e.role}.",
            },
        )
    audit.record(
        db,
        caller,
        action="invitation.created",
        workspace_id=workspace_id,
        object_type="invitation",
        object_id=row.id,
        summary=f"Invited {row.email} as {row.role}",
        after={"email": row.email, "role": row.role, "expires_at": row.expires_at.isoformat()},
    )
    await db.commit()
    log.info(
        "invitation.created",
        invitation_id=str(row.id),
        workspace_id=str(workspace_id),
        email=row.email,
        role=row.role,
    )
    return InvitationCreated(**_out(row).model_dump(), link=inv.link(cfg.public_url, token))


@router.get("/workspaces/{workspace_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(
    workspace_id: uuid.UUID, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> list[InvitationOut]:
    """The workspace's latest invitations, open ones first; never with a link."""
    _visible(caller, workspace_id)
    caller.require(workspace_id, "admin", action="invitation.list")
    rows = await db.scalars(
        select(Invitation)
        .where(Invitation.workspace_id == workspace_id)
        .order_by(Invitation.created_at.desc())
        .limit(LISTED)
    )
    out = [_out(r) for r in rows]
    return sorted(out, key=lambda o: o.status != "open")


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def revoke_invitation(
    invitation_id: uuid.UUID, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> Response:
    """Revoke an open invitation: its link stops working."""
    # Row-level security hides another workspace's invitations: they answer 404.
    row = await db.get(Invitation, invitation_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "invitation not found")
    caller.require(row.workspace_id, "admin", action="invitation.revoke")
    if inv.status_of(row) != "open":
        return JSONResponse(
            status_code=409,
            content={"detail": "invitation_closed", "message": "This invitation is no longer open."},
        )
    row.revoked_at = datetime.now(UTC)
    audit.record(
        db,
        caller,
        action="invitation.revoked",
        workspace_id=row.workspace_id,
        object_type="invitation",
        object_id=row.id,
        summary=f"Revoked the invitation of {row.email} as {row.role}",
        before={"email": row.email, "role": row.role},
    )
    await db.commit()
    log.info("invitation.revoked", invitation_id=str(row.id), workspace_id=str(row.workspace_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def _other_email(invited: str) -> JSONResponse:
    masked = inv.mask(invited)
    return JSONResponse(
        status_code=403,
        content={
            "detail": "invitation_other_email",
            "email": masked,
            "message": f"This invitation is for {masked}. Sign out and sign in with that address.",
        },
    )


@token_router.post("/lookup", response_model=InvitationLookup)
async def lookup(
    body: TokenIn, request: Request, principal: Principal = Depends(signed_in)
) -> InvitationLookup | JSONResponse:
    """What a link does, for the page that accepts it. A POST, so the token stays out of URLs."""
    async with _db(request).system() as db:
        try:
            row = await inv.find(db, body.token)
            inv.usable(row)
        except inv.InvalidInvitationError:
            return JSONResponse(status_code=404, content=INVALID)
        except inv.UsedInvitationError:
            return JSONResponse(status_code=409, content=USED)
        ws = await db.get(Workspace, row.workspace_id)
        by = await db.get(User, row.created_by) if row.created_by else None
    assert ws is not None  # the invitation cascades with its workspace
    return InvitationLookup(
        workspace=WorkspaceRef(id=ws.id, name=ws.name),
        role=row.role,
        email=inv.mask(row.email),
        invited_by=by.display_name if by else None,
        expires_at=row.expires_at,
    )


@token_router.post("/accept", response_model=InvitationAccepted)
async def accept(
    body: TokenIn, request: Request, principal: Principal = Depends(signed_in)
) -> InvitationAccepted | JSONResponse:
    """Accept for the signed-in person, whose email must be the invited one."""
    if principal.user_id is None or principal.email is None:
        return JSONResponse(status_code=409, content=NEEDS_SIGN_IN)
    async with _db(request).system() as db:
        try:
            done = await inv.accept(db, body.token, user_id=principal.user_id, email=principal.email)
        except inv.InvalidInvitationError:
            return JSONResponse(status_code=404, content=INVALID)
        except inv.UsedInvitationError:
            return JSONResponse(status_code=409, content=USED)
        except inv.OtherEmailError as e:
            return _other_email(e.invited)
        row = done.invitation
        audit.record(
            db,
            principal,
            action="invitation.accepted",
            workspace_id=row.workspace_id,
            object_type="invitation",
            object_id=row.id,
            summary=f"{row.email} accepted the invitation as {row.role}",
            after={"email": row.email, "role": row.role},
        )
        if done.before != done.role:
            audit.record(
                db,
                principal,
                action="membership.added" if done.before is None else "membership.changed",
                workspace_id=row.workspace_id,
                object_type="membership",
                object_id=principal.user_id,
                summary=f"Added {row.email} as {done.role} by invitation"
                if done.before is None
                else f"Changed {row.email} from {done.before} to {done.role} by invitation",
                before=None if done.before is None else {"role": done.before, "email": row.email},
                after={"role": done.role, "email": row.email},
            )
        ws = await db.get(Workspace, row.workspace_id)
        await db.commit()
    assert ws is not None
    log.info(
        "invitation.accepted",
        invitation_id=str(row.id),
        workspace_id=str(row.workspace_id),
        user_id=str(principal.user_id),
        before=done.before,
        role=done.role,
    )
    return InvitationAccepted(workspace=WorkspaceRef(id=ws.id, name=ws.name), role=done.role)
