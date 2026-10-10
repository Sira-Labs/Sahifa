"""The audit log (spec 018): one entry per change a person makes, in the change's transaction.

Routes call `record` before they commit, so the entry and the change succeed or fail together.
Each action records the fields spec 018 lists for it and nothing else: never a credential's
value, never a data example.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import Access
from ..auth.deps import actor_of
from ..db.models import AuditEvent

# The past-tense verb of each check and finding action, for summaries.
VERBS = {
    "approve": "Approved",
    "reject": "Rejected",
    "lock": "Locked",
    "unlock": "Unlocked",
    "retire": "Retired",
    "restore": "Restored",
    "acknowledge": "Acknowledged",
    "resolve": "Resolved",
    "mute": "Muted",
    "unmute": "Unmuted",
    "reopen": "Reopened",
}


def record(
    db: AsyncSession,
    caller: Access,
    *,
    action: str,
    workspace_id: uuid.UUID,
    object_type: str,
    object_id: uuid.UUID,
    summary: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add the entry to the session; it is written with the route's commit."""
    event = AuditEvent(
        workspace_id=workspace_id,
        user_id=caller.principal.user_id,
        actor=actor_of(caller.principal),
        action=action,
        object_type=object_type,
        object_id=object_id,
        summary=summary,
        before=before,
        after=after,
    )
    db.add(event)
    return event


def where(asset_label: str, column: str | None) -> str:
    """`orders.amount`, or the asset alone for a table-level check."""
    return f"{asset_label}.{column}" if column else asset_label


def changed(
    before: dict[str, Any] | None, after: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The fields that differ, before and after; everything after when there was nothing."""
    if before is None:
        return None, after
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after[k] for k in keys}
