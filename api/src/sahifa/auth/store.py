"""Login flows, users and sessions in the database (spec 006).

Ported from Tabayyun's `tabayyun.auth.store`. Sahifa has no orgs and no row-level security
yet, so the user is written with plain statements instead of a SECURITY DEFINER function, and
access is not stored at all: it follows the settings at each request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuthSession, LoginFlow, User

FLOW_TTL = timedelta(minutes=10)
# `last_seen_at` is written at most this often per session.
TOUCH_INTERVAL = timedelta(minutes=1)
# Serialises sign-ins, so linking by email and creating users cannot race.
LOGIN_LOCK = "sahifa.login"


class EmailTakenError(Exception):
    """The identity's new email already belongs to another user."""


@dataclass(frozen=True)
class Flow:
    """A sign-in between `/api/auth/login` and the callback."""

    state: str
    nonce: str
    code_verifier: str
    method: str
    next_path: str


@dataclass(frozen=True)
class SignedIn:
    """The user a sign-in resolved to."""

    user_id: uuid.UUID
    email: str
    display_name: str


@dataclass(frozen=True)
class CurrentSession:
    """A live session and the user it belongs to."""

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    sign_in_method: str
    created_at: datetime
    last_seen_at: datetime
    id_token: str | None


async def create_flow(db: AsyncSession, id_hash: bytes, flow: Flow) -> None:
    """Store a new flow and drop the expired ones."""
    await db.execute(delete(LoginFlow).where(LoginFlow.created_at < func.now() - FLOW_TTL))
    db.add(
        LoginFlow(
            id_hash=id_hash,
            state=flow.state,
            nonce=flow.nonce,
            code_verifier=flow.code_verifier,
            method=flow.method,
            next_path=flow.next_path,
        )
    )


async def take_flow(db: AsyncSession, id_hash: bytes) -> tuple[Flow, bool] | None:
    """Delete the flow and return it with whether it is still within FLOW_TTL (single use)."""
    row = (
        await db.execute(
            delete(LoginFlow)
            .where(LoginFlow.id_hash == id_hash)
            .returning(
                LoginFlow.state,
                LoginFlow.nonce,
                LoginFlow.code_verifier,
                LoginFlow.method,
                LoginFlow.next_path,
                LoginFlow.created_at > func.now() - FLOW_TTL,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return Flow(row[0], row[1], row[2], row[3], row[4]), bool(row[5])


async def login(db: AsyncSession, *, issuer: str, subject: str, email: str, display_name: str) -> SignedIn:
    """Find the user by identity, else link by (verified) email, else create one.

    The caller has checked `email_verified`. Raises EmailTakenError when a known identity
    arrives with an email another user holds.
    """
    email = email.strip().lower()
    name = display_name.strip() or email
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": LOGIN_LOCK})
    user = await db.scalar(select(User).where(User.issuer == issuer, User.subject == subject))
    if user is None:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, display_name=name, issuer=issuer, subject=subject)
            db.add(user)
        else:
            # A new identity for a known email: the realm links only verified emails.
            user.issuer, user.subject = issuer, subject
    elif user.email != email:
        holder = await db.scalar(select(User.id).where(User.email == email, User.id != user.id))
        if holder is not None:
            raise EmailTakenError(email)
        user.email = email
    user.display_name = name
    user.last_login_at = func.now()
    await db.flush()
    return SignedIn(user_id=user.id, email=email, display_name=name)


async def create_session(
    db: AsyncSession,
    *,
    id_hash: bytes,
    user_id: uuid.UUID,
    sign_in_method: str,
    idp_sid: str | None,
    id_token: str | None,
    ip_address: str | None,
    user_agent: str | None,
    absolute: timedelta,
    idle: timedelta,
) -> None:
    """Add a session and prune the user's dead ones (revoked, idle or past their lifetime)."""
    await db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user_id,
            or_(
                AuthSession.revoked_at.is_not(None),
                AuthSession.expires_at < func.now(),
                AuthSession.last_seen_at < func.now() - idle,
            ),
        )
    )
    db.add(
        AuthSession(
            id_hash=id_hash,
            user_id=user_id,
            sign_in_method=sign_in_method,
            idp_sid=idp_sid,
            id_token=id_token,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=func.now() + absolute,
        )
    )


async def find_session(db: AsyncSession, id_hash: bytes, *, idle: timedelta) -> CurrentSession | None:
    """The live session with this hash (not revoked, idle or expired), touched at most once a
    minute; None otherwise."""
    row = (
        await db.execute(
            select(AuthSession, User.email, User.display_name)
            .join(User, User.id == AuthSession.user_id)
            .where(
                AuthSession.id_hash == id_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > func.now(),
                AuthSession.last_seen_at > func.now() - idle,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    session, email, display_name = row
    current = CurrentSession(
        id=session.id,
        user_id=session.user_id,
        email=email,
        display_name=display_name,
        sign_in_method=session.sign_in_method,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        id_token=session.id_token,
    )
    # Read the row first, and keep the ORM from syncing it: a matched UPDATE would expire
    # `last_seen_at` on the loaded object, and reading it again would need lazy IO, which an
    # async session refuses (MissingGreenlet on every request after the first minute).
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == session.id, AuthSession.last_seen_at < func.now() - TOUCH_INTERVAL)
        .values(last_seen_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return current


async def list_sessions(db: AsyncSession, user_id: uuid.UUID, *, idle: timedelta) -> list[AuthSession]:
    """The user's live sessions, most recently used first."""
    rows = await db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > func.now(),
            AuthSession.last_seen_at > func.now() - idle,
        )
        .order_by(AuthSession.last_seen_at.desc(), AuthSession.created_at.desc())
    )
    return list(rows)


async def revoke(db: AsyncSession, session_id: uuid.UUID, *, user_id: uuid.UUID) -> bool:
    """Revoke one of the user's sessions; False when it is not theirs or already revoked."""
    result = await db.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .returning(AuthSession.id)
    )
    return result.first() is not None


async def revoke_user_sessions(db: AsyncSession, user_id: uuid.UUID, *, keep: uuid.UUID | None = None) -> int:
    """Revoke every live session of the user except `keep`; returns how many."""
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .returning(AuthSession.id)
    )
    if keep is not None:
        stmt = stmt.where(AuthSession.id != keep)
    return len((await db.execute(stmt)).all())


async def revoke_by_idp(db: AsyncSession, *, issuer: str, sid: str | None, subject: str | None) -> int:
    """Back-channel logout: revoke the sessions of the IdP session `sid`, or without one, every
    session of the identity `subject`; returns how many."""
    stmt = update(AuthSession).where(AuthSession.revoked_at.is_(None)).values(revoked_at=func.now())
    if sid:
        stmt = stmt.where(AuthSession.idp_sid == sid)
    elif subject:
        owner = select(User.id).where(User.issuer == issuer, User.subject == subject)
        stmt = stmt.where(AuthSession.user_id.in_(owner.scalar_subquery()))
    else:
        return 0
    return len((await db.execute(stmt.returning(AuthSession.id))).all())
