"""Assets, columns and checks of a connection (spec 007): loading saved checks for a scan,
persisting a scan's checks, and the lifecycle transitions of ADR-0005.

Every name from the source (asset, column, check key) is stored as text through bound
parameters; parameter values are never logged, because they can hold values from the data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Asset, AssetColumn, Check, CheckEvent

if TYPE_CHECKING:
    from sahifa_core.models import CheckSpec

SCANNER = "scanner"
# action → (from, to); ADR-0005 and spec 007.
TRANSITIONS: dict[str, tuple[str, str]] = {
    "approve": ("proposed", "active"),
    "reject": ("proposed", "retired"),
    "lock": ("active", "locked"),
    "unlock": ("locked", "active"),
    "retire": ("active", "retired"),
    "restore": ("retired", "active"),
}
# What a scan may regenerate: generated checks still open to new parameters.
REGENERABLE = ("proposed", "active")


def label_of(namespace: str, name: str) -> str:
    """The core's `AssetRef.label` (lossless: parts with a dot or quote are quoted)."""
    from sahifa_core.models import label_of as core_label_of

    return core_label_of(namespace, name)


@dataclass
class Saved:
    """The checks of a connection when its scan starts: specs per asset label for the core,
    and each check's version for the optimistic guard of the persist step."""

    specs: dict[str, list[CheckSpec]]
    versions: dict[uuid.UUID, int]


def to_spec(check: Check, asset: Asset) -> CheckSpec:
    """A stored check as the core's `CheckSpec`."""
    from sahifa_core.models import AssetRef, CheckSpec

    return CheckSpec(
        id=check.key,
        type=check.type,
        asset=AssetRef(namespace=asset.namespace, name=asset.name, kind=asset.kind),  # type: ignore[arg-type]
        column=check.column_name,
        columns=list(check.columns or []),
        params=dict(check.params or {}),
        dimension=check.dimension,  # type: ignore[arg-type]
        severity=check.severity,  # type: ignore[arg-type]
        kind=check.kind,  # type: ignore[arg-type]
        status=check.status,  # type: ignore[arg-type]
        max_fail_ratio=check.max_fail_ratio,
        origin=check.origin,  # type: ignore[arg-type]
    )


async def load_saved(db: AsyncSession, connection_id: uuid.UUID) -> Saved:
    """Every check of every asset of the connection, retired ones included (behaviour 1)."""
    rows = (
        await db.execute(
            select(Check, Asset)
            .join(Asset, Asset.id == Check.asset_id)
            .where(Asset.connection_id == connection_id)
        )
    ).all()
    specs: dict[str, list[CheckSpec]] = {}
    versions: dict[uuid.UUID, int] = {}
    for check, asset in rows:
        specs.setdefault(asset.label, []).append(to_spec(check, asset))
        versions[check.id] = check.version
    return Saved(specs=specs, versions=versions)


@dataclass
class Persisted:
    inserted: int = 0
    regenerated: int = 0
    skipped: int = 0


def _generated(spec: dict[str, Any]) -> dict[str, Any]:
    """What a scan may change on an existing generated check."""
    return {
        "params": spec.get("params") or {},
        "columns": spec.get("columns") or [],
        "severity": spec["severity"],
        "max_fail_ratio": spec.get("max_fail_ratio", 0.0),
    }


async def _upsert_asset(
    db: AsyncSession, connection_id: uuid.UUID, scan_id: uuid.UUID, asset: dict[str, Any]
) -> uuid.UUID:
    ref = asset["ref"]
    values: dict[str, Any] = {
        "kind": ref.get("kind", "table"),
        "last_scan_id": scan_id,
        "updated_at": func.now(),
    }
    if not asset.get("error"):
        values["row_count"] = asset.get("population")
    stmt = (
        insert(Asset)
        .values(connection_id=connection_id, namespace=ref.get("namespace", ""), name=ref["name"], **values)
        .on_conflict_do_update(constraint="uq_assets_connection_namespace_name", set_=values)
        .returning(Asset.id)
    )
    asset_id: uuid.UUID = (await db.execute(stmt)).scalar_one()
    if not asset.get("error"):
        await db.execute(delete(AssetColumn).where(AssetColumn.asset_id == asset_id))
        columns = [
            {
                "asset_id": asset_id,
                "name": c["profile"]["name"],
                "position": c["profile"]["position"],
                "physical_type": c["profile"]["physical_type"],
                "logical_type": c["profile"]["logical_type"],
                "semantic_type": c["profile"].get("semantic_type"),
                "role": c["profile"].get("role", "attribute"),
            }
            for c in asset.get("columns", [])
        ]
        if columns:
            await db.execute(insert(AssetColumn), columns)
    return asset_id


async def persist_checks(
    db: AsyncSession,
    *,
    scan_id: uuid.UUID,
    connection_id: uuid.UUID,
    report: dict[str, Any],
    versions: dict[uuid.UUID, int],
) -> Persisted:
    """Upsert the report's assets, columns and checks inside the caller's transaction
    (behaviours 3 and 4). `versions` are the check versions loaded when the scan started: a check
    changed since then (by a person) is skipped, and locked, retired and manual checks keep
    their status and parameters. Nothing is deleted."""
    out = Persisted()
    by_label: dict[str, list[dict[str, Any]]] = {}
    for spec in report.get("checks", []):
        ref = spec["asset"]
        by_label.setdefault(label_of(ref.get("namespace", ""), ref["name"]), []).append(spec)
    for asset in report.get("assets", []):
        ref = asset["ref"]
        asset_id = await _upsert_asset(db, connection_id, scan_id, asset)
        specs = by_label.get(label_of(ref.get("namespace", ""), ref["name"]), [])
        if not specs:
            continue
        existing = {
            c.key: c
            for c in await db.scalars(
                select(Check).where(Check.asset_id == asset_id, Check.key.in_([s["id"] for s in specs]))
            )
        }
        for spec in specs:
            row = existing.get(spec["id"])
            if row is None:
                await _insert(db, out, asset_id, scan_id, spec)
                continue
            if versions.get(row.id) != row.version:
                out.skipped += 1  # changed after the scan loaded it: the newer change wins
                continue
            fresh, before = _generated(spec), row.params
            changed = (
                row.status in REGENERABLE
                and row.origin != "manual"
                and any(getattr(row, k) != v for k, v in fresh.items())
            )
            values: dict[str, Any] = {"last_scan_id": scan_id}
            if changed:
                values |= fresh | {"version": Check.version + 1, "updated_at": func.now()}
            done = await db.execute(
                update(Check)
                .where(Check.id == row.id, Check.version == row.version)
                .values(**values)
                .returning(Check.id)
                .execution_options(synchronize_session=False)
            )
            if done.scalar_one_or_none() is None:
                out.skipped += 1
                continue
            if changed:
                out.regenerated += 1
                db.add(
                    CheckEvent(
                        check_id=row.id,
                        actor=SCANNER,
                        action="regenerated",
                        from_status=row.status,
                        to_status=row.status,
                        params_before=before,
                        params_after=fresh["params"],
                    )
                )
    await db.flush()
    return out


async def _insert(
    db: AsyncSession, out: Persisted, asset_id: uuid.UUID, scan_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    """A new check with its `created` event; a concurrent scan that inserted it first wins."""
    stmt = (
        insert(Check)
        .values(
            asset_id=asset_id,
            key=spec["id"],
            type=spec["type"],
            column_name=spec.get("column"),
            dimension=spec["dimension"],
            kind=spec["kind"],
            origin=spec.get("origin", "generated"),
            status=spec["status"],
            last_scan_id=scan_id,
            **_generated(spec),
        )
        .on_conflict_do_nothing(constraint="uq_checks_asset_key")
        .returning(Check.id)
    )
    check_id = (await db.execute(stmt)).scalar_one_or_none()
    if check_id is None:
        out.skipped += 1
        return
    out.inserted += 1
    db.add(
        CheckEvent(
            check_id=check_id,
            actor=SCANNER,
            action="created",
            from_status=None,
            to_status=spec["status"],
            params_after=spec.get("params") or {},
        )
    )
