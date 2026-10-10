"""Who may see and change what (spec 016, ADR-0010): workspaces, memberships and roles.

`current_access` resolves once per request which workspaces the principal sees and their role
in each. Request sessions see only those workspaces under row-level security (`deps.session`),
so an object elsewhere gives 404; routes that change something call `Access.require`, which
gives 403 `forbidden_role` below the action's minimum role.

Org admins (`SAHIFA_ADMIN_EMAIL`, and the single principal in `dev` and `proxy` mode) see every
workspace with the role `admin`; they are not stored as members.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TypeVar

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ROLES, Membership, Workspace
from ..logging import get_logger
from ..schemas import InWorkspace, WorkspaceRef
from ..settings import Settings
from .deps import NoAccessError, Principal, factory_of, settings_of, signed_in

log = get_logger("sahifa.rbac")

Out = TypeVar("Out", bound=InWorkspace)
RANK = {role: i for i, role in enumerate(ROLES, start=1)}
_STATE_KEY = "sahifa_access"


@dataclass(frozen=True)
class WorkspaceRole:
    """A workspace the principal sees, with their role there."""

    id: uuid.UUID
    name: str
    role: str
    is_default: bool


class ForbiddenRoleError(Exception):
    """The principal's role in the workspace is below what the action needs."""

    def __init__(self, role: str | None, needs: str) -> None:
        super().__init__(f"{role} < {needs}")
        self.role = role
        self.needs = needs

    def body(self) -> dict[str, str | None]:
        return {"detail": "forbidden_role", "role": self.role, "needs": self.needs}


class WorkspaceRequiredError(Exception):
    """The caller may act in several workspaces and named none."""


@dataclass(frozen=True)
class Access:
    """The principal and the workspaces they see, by id."""

    principal: Principal
    org_admin: bool
    workspaces: dict[uuid.UUID, WorkspaceRole] = field(default_factory=dict)

    def role_in(self, workspace_id: uuid.UUID) -> str | None:
        found = self.workspaces.get(workspace_id)
        return found.role if found else None

    def name_of(self, workspace_id: uuid.UUID) -> str | None:
        found = self.workspaces.get(workspace_id)
        return found.name if found else None

    def stamp(self, out: Out, workspace_id: uuid.UUID) -> Out:
        """Set the workspace and the caller's role there on an output."""
        out.workspace = WorkspaceRef(id=workspace_id, name=self.name_of(workspace_id) or "")
        out.role = self.role_in(workspace_id)
        return out

    def allows(self, workspace_id: uuid.UUID, needs: str) -> bool:
        return RANK.get(self.role_in(workspace_id) or "", 0) >= RANK[needs]

    def require(self, workspace_id: uuid.UUID, needs: str, *, action: str) -> None:
        """403 `forbidden_role` unless the principal has at least `needs` in the workspace."""
        if self.allows(workspace_id, needs):
            return
        role = self.role_in(workspace_id)
        log.info(
            "rbac.denied",
            user_id=str(self.principal.user_id) if self.principal.user_id else None,
            workspace_id=str(workspace_id),
            action=action,
            role=role,
            needs=needs,
        )
        raise ForbiddenRoleError(role, needs)

    def pick(self, workspace_id: uuid.UUID | None, needs: str, *, action: str) -> uuid.UUID:
        """The workspace a new object goes to: the one named, checked; else the only one where
        the principal has `needs`. 404 for a workspace they do not see, 403 when there is none,
        `WorkspaceRequiredError` when there are several."""
        if workspace_id is not None:
            if workspace_id not in self.workspaces:
                raise HTTPException(404, "workspace not found")
            self.require(workspace_id, needs, action=action)
            return workspace_id
        able = [w.id for w in self.workspaces.values() if self.allows(w.id, needs)]
        if len(able) == 1:
            return able[0]
        if not able:
            best = max((w.role for w in self.workspaces.values()), key=RANK.__getitem__, default=None)
            log.info(
                "rbac.denied",
                user_id=str(self.principal.user_id) if self.principal.user_id else None,
                action=action,
                role=best,
                needs=needs,
            )
            raise ForbiddenRoleError(best, needs)
        raise WorkspaceRequiredError


async def _all_workspaces(db: AsyncSession) -> dict[uuid.UUID, WorkspaceRole]:
    rows = await db.scalars(select(Workspace).order_by(Workspace.name))
    return {w.id: WorkspaceRole(w.id, w.name, "admin", w.is_default) for w in rows}


async def _memberships(db: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, WorkspaceRole]:
    rows = await db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user_id)
        .order_by(Workspace.name)
    )
    return {w.id: WorkspaceRole(w.id, w.name, role, w.is_default) for w, role in rows.all()}


async def bootstrap_allowed(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Until invitations (S4-3): an allowed email without a membership becomes an editor of the
    default workspace. False when there is nothing to add."""
    default = await db.scalar(select(Workspace.id).where(Workspace.is_default))
    if default is None:
        return False
    stmt = (
        insert(Membership)
        .values(workspace_id=default, user_id=user_id, role="editor")
        .on_conflict_do_nothing()
        .returning(Membership.role)
    )
    added = (await db.execute(stmt)).first() is not None
    if added:
        log.info(
            "membership.changed",
            user_id=str(user_id),
            workspace_id=str(default),
            role="editor",
            reason="allowed_email",
        )
    return added


async def load_access(db: AsyncSession, settings: Settings, principal: Principal) -> Access | None:
    """The principal's access, or None when they have no workspace at all."""
    if principal.admin:
        return Access(principal, True, await _all_workspaces(db))
    if principal.user_id is None:
        return None
    workspaces = await _memberships(db, principal.user_id)
    if not workspaces and settings.has_access(principal.email):
        await bootstrap_allowed(db, principal.user_id)
        workspaces = await _memberships(db, principal.user_id)
    return Access(principal, False, workspaces) if workspaces else None


async def current_access(request: Request) -> Access:
    """The request's access, resolved once: 401 without a session, 403 `no_access` for a
    signed-in person without any workspace."""
    if hasattr(request.state, _STATE_KEY):
        cached: Access = getattr(request.state, _STATE_KEY)
        return cached
    principal = await signed_in(request)
    async with factory_of(request)() as db, db.begin():
        access = await load_access(db, settings_of(request), principal)
    if access is None:
        log.info("auth.denied", reason="no_access", user_id=str(principal.user_id), path=request.url.path)
        raise NoAccessError(principal.email)
    setattr(request.state, _STATE_KEY, access)
    return access
