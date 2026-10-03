"""Findings across scans (spec 009): linking a scan's failing checks to their findings,
resolving the findings of checks that pass again, and the status transitions people make.

A scan records one occurrence per failing check, as before, and links it to the check's
finding: the one that is not resolved, else the most recent resolved one (reopened), else a
new one. Evidence and notes are never logged: examples can hold values from the data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Check, Finding, FindingEvent, FindingOccurrence
from .checks import SCANNER, label_of

# action → (allowed from, to); spec 009.
TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "acknowledge": (("open",), "acknowledged"),
    "resolve": (("open", "acknowledged", "muted"), "resolved"),
    "mute": (("open", "acknowledged"), "muted"),
    "unmute": (("muted",), "open"),
    "reopen": (("resolved",), "open"),
}
# Check statuses that count toward scores and findings (ADR-0005).
SCORING = ("active", "locked")
SEVERITIES = ("critical", "high", "medium", "low")
UNRESOLVED = text("status <> 'resolved'")
# Attempts to link one failing check when concurrent scans of the connection race (behaviour 5).
ATTEMPTS = 3


@dataclass
class Linked:
    """What linking one scan's findings changed (the `scan.findings_linked` log line)."""

    opened: int = 0
    recurred: int = 0
    reopened: int = 0
    unmuted: int = 0
    auto_resolved: int = 0
    unlinked: int = 0


def occurrence_of(scan_id: uuid.UUID, f: dict[str, Any], finding_id: uuid.UUID | None) -> FindingOccurrence:
    """A core finding as one occurrence row, with its evidence."""
    return FindingOccurrence(
        scan_id=scan_id,
        finding_id=finding_id,
        check_type=f["check_type"],
        asset=f["asset"],
        column_name=f.get("column"),
        dimension=f["dimension"],
        severity=f["severity"],
        evaluated=f["evaluated"],
        failed=f["failed"],
        ratio=f["ratio"],
        low=f["low"],
        high=f["high"],
        summary=f["summary"],
        next_step=f["next_step"],
        evidence={
            "check_id": f["check_id"],
            "title": f.get("title"),
            "examples": f.get("examples", []),
            "sql": f.get("sql"),
        },
    )


def passed_keys(report: dict[str, Any]) -> set[tuple[str, str]]:
    """(asset label, check key) of every check that was evaluated in this scan and passed.

    - **Evaluated**: the check has a result in `assets[].checks` of an asset without `error`.
      Retired checks, saved checks that could not run (`assets[].unevaluated`), generated
      candidates dropped for weak evidence and every check of a failed asset have none.
    - **Passed**: the result's check scores (`active` or `locked`) and is not a finding, i.e.
      it found no failures or stayed within its tolerance (the inverse of the core's
      `is_finding`: `failed > 0 and not passed`).
    """
    out: set[tuple[str, str]] = set()
    for asset in report.get("assets", []):
        if asset.get("error"):
            continue
        for r in asset.get("checks", []):
            spec = r["spec"]
            if spec["status"] not in SCORING or (r["failed"] > 0 and not r["passed"]):
                continue
            ref = spec["asset"]
            out.add((label_of(ref.get("namespace", ""), ref["name"]), spec["id"]))
    return out


def _event(finding: Finding, action: str, before: str | None) -> FindingEvent:
    return FindingEvent(
        finding_id=finding.id, actor=SCANNER, action=action, from_status=before, to_status=finding.status
    )


def _recur(
    db: AsyncSession, out: Linked, f: Finding, scan_id: uuid.UUID, seen_at: datetime, severity: str
) -> uuid.UUID:
    """Behaviour 1.1: one more occurrence of a finding that is not resolved."""
    before = f.status
    f.occurrences += 1
    f.last_scan_id, f.last_seen_at, f.severity = scan_id, seen_at, severity
    f.version += 1
    f.updated_at = seen_at
    if f.status == "muted" and f.muted_until is not None and f.muted_until <= seen_at:
        f.status, f.muted_until = "open", None
        out.unmuted += 1
        db.add(_event(f, "unmuted", before))
    else:
        out.recurred += 1
        db.add(_event(f, "recurred", before))
    return f.id


async def _link(
    db: AsyncSession, out: Linked, check_id: uuid.UUID, scan_id: uuid.UUID, seen_at: datetime, severity: str
) -> uuid.UUID:
    """The finding of a failing check after this scan (behaviours 1 and 5), its row locked."""
    for _ in range(ATTEMPTS):
        current = await db.scalar(
            select(Finding)
            .where(Finding.check_id == check_id, Finding.status != "resolved")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is not None:
            return _recur(db, out, current, scan_id, seen_at, severity)
        last = await db.scalar(
            select(Finding)
            .where(Finding.check_id == check_id, Finding.status == "resolved")
            .order_by(Finding.resolved_at.desc().nulls_last(), Finding.created_at.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if last is not None:
            # Earlier rows go out first: a rolled-back savepoint would discard them too.
            await db.flush()
            try:
                async with db.begin_nested():
                    last.status = "open"
                    last.occurrences += 1
                    last.last_scan_id, last.last_seen_at, last.severity = scan_id, seen_at, severity
                    last.resolved_at = last.resolved_scan_id = last.muted_until = None
                    last.version += 1
                    last.updated_at = seen_at
                    await db.flush()
            except IntegrityError:
                continue  # a concurrent scan opened a finding for this check first: recur on it
            out.reopened += 1
            db.add(_event(last, "reopened", "resolved"))
            return last.id
        new_id = (
            await db.execute(
                insert(Finding)
                .values(
                    check_id=check_id,
                    status="open",
                    severity=severity,
                    occurrences=1,
                    first_scan_id=scan_id,
                    last_scan_id=scan_id,
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                )
                .on_conflict_do_nothing(index_elements=["check_id"], index_where=UNRESOLVED)
                .returning(Finding.id)
            )
        ).scalar_one_or_none()
        if new_id is None:
            continue  # inserted by a concurrent scan of the same connection: recur on it
        out.opened += 1
        db.add(FindingEvent(finding_id=new_id, actor=SCANNER, action="opened", to_status="open"))
        return new_id
    raise RuntimeError("could not link a finding to its check after concurrent changes")


async def record_findings(
    db: AsyncSession,
    *,
    scan_id: uuid.UUID,
    seen_at: datetime,
    report: dict[str, Any],
    asset_ids: dict[str, uuid.UUID],
) -> Linked:
    """Write the scan's occurrences and update its findings inside the caller's transaction,
    after `persist_checks` (behaviours 1, 2 and 3). `asset_ids` maps each asset label of the
    report to its stored id.

    A check whose stored status no longer scores (a person retired it while the scan ran) keeps
    its finding unchanged: its occurrence is recorded without a link, and the person's newer
    decision wins, as for the checks themselves (spec 007)."""
    out = Linked()
    labels = {aid: label for label, aid in asset_ids.items()}
    checks: dict[tuple[str, str], tuple[uuid.UUID, str]] = {}
    if labels:
        rows = await db.execute(
            select(Check.id, Check.asset_id, Check.key, Check.status).where(Check.asset_id.in_(list(labels)))
        )
        checks = {(labels[aid], key): (cid, status) for cid, aid, key, status in rows.all()}

    for f in report.get("findings", []):
        hit = checks.get((f["asset"], f["check_id"]))
        finding_id = None
        if hit is not None and hit[1] in SCORING:
            finding_id = await _link(db, out, hit[0], scan_id, seen_at, f["severity"])
        else:
            out.unlinked += 1
        db.add(occurrence_of(scan_id, f, finding_id))

    passing = [checks[k][0] for k in passed_keys(report) if k in checks and checks[k][1] in SCORING]
    if passing:
        resolvable = await db.scalars(
            select(Finding)
            .where(Finding.check_id.in_(passing), Finding.status != "resolved")
            .order_by(Finding.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for f in resolvable:
            before = f.status
            f.status, f.resolved_at, f.resolved_scan_id, f.muted_until = "resolved", seen_at, scan_id, None
            f.version += 1
            f.updated_at = seen_at
            out.auto_resolved += 1
            db.add(_event(f, "auto_resolved", before))
    await db.flush()
    return out
