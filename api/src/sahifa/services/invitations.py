"""Invitations by link (spec 020): create, look up, accept and revoke.

The link carries a random token after `#`; the database holds only its SHA-256. A token is the
proof that its holder was invited, so looking one up and accepting it read the table as the
system: the invited person is not in the workspace yet, and row-level security would hide it.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import RANK
from ..auth.tokens import new_token
from ..db.models import Invitation, Membership, User

INVITE_PATH = "/invite"


class AlreadyMemberError(Exception):
    """The address is a member at the invited role or higher."""

    def __init__(self, role: str) -> None:
        super().__init__(role)
        self.role = role


class InvalidInvitationError(Exception):
    """Unknown, revoked or expired: one error for all three, so a token cannot be probed."""


class UsedInvitationError(Exception):
    """Accepted already."""


class OtherEmailError(Exception):
    """Signed in with another address than the invited one."""

    def __init__(self, invited: str) -> None:
        super().__init__(invited)
        self.invited = invited


@dataclass(frozen=True)
class Accepted:
    invitation: Invitation
    before: str | None  # the role before, None for a new member
    role: str  # the role after; never lower than before


def hash_token(token: str) -> bytes:
    """What the database stores: SHA-256 of a 32-byte random token needs no key."""
    return hashlib.sha256(token.encode()).digest()


def link(public_url: str | None, token: str) -> str:
    """The link to send: the token after `#`, which browsers keep out of requests and logs."""
    return f"{(public_url or '').rstrip('/')}{INVITE_PATH}#{token}"


def mask(email: str) -> str:
    """`b***@example.org`: enough to recognise one's address, not to read someone else's."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def status_of(inv: Invitation, now: datetime | None = None) -> str:
    if inv.accepted_at is not None:
        return "accepted"
    if inv.revoked_at is not None:
        return "revoked"
    if inv.expires_at <= (now or datetime.now(UTC)):
        return "expired"
    return "open"


async def create(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    email: str,
    role: str,
    created_by: uuid.UUID | None,
    ttl_days: int,
) -> tuple[Invitation, str]:
    """A new invitation and its token, shown once. An open invitation for the same address is
    revoked: its link stops working."""
    email = email.strip().lower()
    member_role = await db.scalar(
        select(Membership.role)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id, User.email == email)
    )
    if member_role is not None and RANK[member_role] >= RANK[role]:
        raise AlreadyMemberError(member_role)
    now = datetime.now(UTC)
    await db.execute(
        update(Invitation)
        .where(
            Invitation.workspace_id == workspace_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    token = new_token()
    inv = Invitation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        created_by=created_by,
        created_at=now,
        expires_at=now + timedelta(days=ttl_days),
    )
    db.add(inv)
    return inv, token


async def find(db: AsyncSession, token: str, *, for_update: bool = False) -> Invitation:
    """The invitation behind a token, whatever its state, or `InvalidInvitationError`."""
    stmt = select(Invitation).where(Invitation.token_hash == hash_token(token))
    if for_update:
        stmt = stmt.with_for_update()
    inv = await db.scalar(stmt)
    if inv is None:
        raise InvalidInvitationError
    return inv


def usable(inv: Invitation) -> None:
    """Raise unless the invitation can still be accepted."""
    state = status_of(inv)
    if state == "accepted":
        raise UsedInvitationError
    if state != "open":
        raise InvalidInvitationError


async def accept(db: AsyncSession, token: str, *, user_id: uuid.UUID, email: str) -> Accepted:
    """Accept for the signed-in person: create the membership or raise its role, never lower it,
    and mark the invitation accepted, all in the caller's transaction."""
    inv = await find(db, token, for_update=True)
    usable(inv)
    if email.strip().lower() != inv.email:
        raise OtherEmailError(inv.email)
    member = await db.get(Membership, (inv.workspace_id, user_id), with_for_update=True)
    before = member.role if member else None
    if member is None:
        db.add(
            Membership(
                workspace_id=inv.workspace_id, user_id=user_id, role=inv.role, created_by=inv.created_by
            )
        )
        role = inv.role
    elif RANK[inv.role] > RANK[member.role]:
        member.role = role = inv.role
    else:
        role = member.role
    inv.accepted_at = datetime.now(UTC)
    inv.accepted_by = user_id
    return Accepted(invitation=inv, before=before, role=role)
