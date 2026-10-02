"""Scans (spec 004): create on a connection or on uploaded files, list, read, report, findings."""

from __future__ import annotations

import base64
import json
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Connection, Finding, Scan
from ..deps import session, settings
from ..logging import get_logger
from ..schemas import Items, Page, ScanIn, ScanOut, ScanScore
from ..settings import Settings

router = APIRouter(prefix="/api/scans", tags=["scans"])
log = get_logger("sahifa.scans")

UPLOAD_EXTENSIONS = frozenset({".csv", ".tsv", ".parquet", ".json", ".jsonl", ".ndjson"})
CHUNK = 1024 * 1024
SEVERITIES = ("critical", "high", "medium", "low")
DIMENSIONS = ("completeness", "validity", "accuracy", "consistency", "uniqueness", "currentness")


def to_out(scan: Scan, conn: Connection) -> ScanOut:
    score = ScanScore(**scan.score) if scan.score else None
    counts = {s: 0 for s in SEVERITIES} | (scan.finding_counts or {})
    files = conn.config.get("files") if conn.kind == "upload" else None
    return ScanOut(
        id=scan.id,
        connection_id=conn.id,
        connection_name=conn.name,
        connection_kind=conn.kind,
        status=scan.status,
        created_at=scan.created_at,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        error=scan.error,
        sample_rows=scan.sample_rows,
        score=score,
        findings=counts,
        assets_count=scan.assets_count,
        files=files,
    )


async def _enqueue(
    request: Request, db: AsyncSession, conn: Connection, sample_rows: int, options: dict[str, Any]
) -> ScanOut:
    scan = Scan(connection_id=conn.id, sample_rows=sample_rows, options=options, status="queued")
    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    request.app.state.runner.submit(scan.id)
    log.info("scan.queued", scan_id=str(scan.id), connection=conn.name)
    return to_out(scan, conn)


@router.post("", response_model=ScanOut, status_code=status.HTTP_202_ACCEPTED)
async def create_scan(
    body: ScanIn, request: Request, db: AsyncSession = Depends(session), cfg: Settings = Depends(settings)
) -> ScanOut:
    conn = await db.get(Connection, body.connection_id)
    if conn is None or conn.kind == "upload":
        raise HTTPException(404, "connection not found")
    sample = cfg.sample_rows if body.sample_rows is None else body.sample_rows
    return await _enqueue(request, db, conn, sample, {"assets": body.assets})


@router.post("/upload", response_model=ScanOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_scan(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    sample_rows: int | None = Form(default=None, ge=0),
    db: AsyncSession = Depends(session),
    cfg: Settings = Depends(settings),
) -> ScanOut:
    if not files:
        raise HTTPException(422, "choose at least one file")
    if len(files) > cfg.max_upload_files:
        raise HTTPException(422, f"at most {cfg.max_upload_files} files per scan")
    for f in files:
        if Path(f.filename or "").suffix.lower() not in UPLOAD_EXTENSIONS:
            raise HTTPException(415, f"{f.filename}: only CSV, TSV, Parquet and JSON files are accepted")
    batch = uuid.uuid4().hex
    folder = cfg.uploads_dir / batch
    folder.mkdir(parents=True, exist_ok=True)
    limit = cfg.max_upload_mb * 1024 * 1024
    paths: list[str] = []
    names: dict[str, str] = {}
    try:
        for f in files:
            original = Path(f.filename or "file").name
            target = folder / f"{secrets.token_hex(8)}{Path(original).suffix.lower()}"
            size = 0
            with target.open("wb") as out:
                while chunk := await f.read(CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"{original} is larger than {cfg.max_upload_mb} MB")
                    out.write(chunk)
            paths.append(str(target))
            names[str(target)] = Path(original).stem
    except HTTPException:
        for p in folder.iterdir():
            p.unlink(missing_ok=True)
        folder.rmdir()
        raise
    originals = [Path(f.filename or "file").name for f in files]
    conn = Connection(
        name=f"upload-{batch}", kind="upload", config={"paths": paths, "names": names, "files": originals}
    )
    db.add(conn)
    await db.flush()
    sample = cfg.sample_rows if sample_rows is None else sample_rows
    return await _enqueue(request, db, conn, sample, {"files": originals})


def _cursor(scan: Scan) -> str:
    raw = json.dumps([scan.created_at.isoformat(), str(scan.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _after(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created, sid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(created), uuid.UUID(sid)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, "invalid cursor") from e


@router.get("", response_model=Page[ScanOut])
async def list_scans(
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = None,
    db: AsyncSession = Depends(session),
) -> Page[ScanOut]:
    stmt = (
        select(Scan, Connection)
        .join(Connection, Connection.id == Scan.connection_id)
        .order_by(Scan.created_at.desc(), Scan.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        created, sid = _after(cursor)
        stmt = stmt.where(or_(Scan.created_at < created, and_(Scan.created_at == created, Scan.id < sid)))
    rows = [(r[0], r[1]) for r in (await db.execute(stmt)).all()]
    items = [to_out(s, c) for s, c in rows[:limit]]
    nxt = _cursor(rows[limit - 1][0]) if len(rows) > limit else None
    return Page[ScanOut](items=items, next_cursor=nxt)


async def _scan(db: AsyncSession, scan_id: uuid.UUID) -> tuple[Scan, Connection]:
    row = (
        await db.execute(
            select(Scan, Connection)
            .join(Connection, Connection.id == Scan.connection_id)
            .where(Scan.id == scan_id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "scan not found")
    return row[0], row[1]


@router.get("/{scan_id}", response_model=ScanOut)
async def get_scan(scan_id: uuid.UUID, db: AsyncSession = Depends(session)) -> ScanOut:
    scan, conn = await _scan(db, scan_id)
    return to_out(scan, conn)


@router.get("/{scan_id}/report")
async def get_report(scan_id: uuid.UUID, db: AsyncSession = Depends(session)) -> dict[str, Any]:
    scan, _ = await _scan(db, scan_id)
    if scan.status != "succeeded" or scan.report is None:
        raise HTTPException(409, f"the scan is {scan.status}; the report exists once it has succeeded")
    return scan.report


@router.get("/{scan_id}/findings", response_model=Items[dict[str, Any]])
async def list_findings(
    scan_id: uuid.UUID,
    severity: str | None = None,
    dimension: str | None = None,
    asset: str | None = None,
    db: AsyncSession = Depends(session),
) -> Items[dict[str, Any]]:
    await _scan(db, scan_id)
    stmt = select(Finding).where(Finding.scan_id == scan_id)
    if severity:
        if severity not in SEVERITIES:
            raise HTTPException(422, f"severity must be one of {', '.join(SEVERITIES)}")
        stmt = stmt.where(Finding.severity == severity)
    if dimension:
        if dimension not in DIMENSIONS:
            raise HTTPException(422, f"dimension must be one of {', '.join(DIMENSIONS)}")
        stmt = stmt.where(Finding.dimension == dimension)
    if asset:
        stmt = stmt.where(Finding.asset == asset)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    rows = sorted(await db.scalars(stmt), key=lambda f: (rank.get(f.severity, 9), f.ratio))
    return Items[dict[str, Any]](
        items=[
            {
                "id": str(f.id),
                "check_id": f.evidence.get("check_id"),
                "check_type": f.check_type,
                "title": f.evidence.get("title"),
                "asset": f.asset,
                "column": f.column_name,
                "dimension": f.dimension,
                "severity": f.severity,
                "evaluated": f.evaluated,
                "failed": f.failed,
                "ratio": f.ratio,
                "low": f.low,
                "high": f.high,
                "summary": f.summary,
                "next_step": f.next_step,
                "examples": f.evidence.get("examples", []),
                "sql": f.evidence.get("sql"),
            }
            for f in rows
        ]
    )
