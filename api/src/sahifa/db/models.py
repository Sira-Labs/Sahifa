"""Tables of migration 0001 (spec 004)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base

CONNECTION_KINDS = ("postgres", "duckdb", "upload")
SCAN_STATUSES = ("queued", "running", "succeeded", "failed")


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (CheckConstraint(f"kind IN {CONNECTION_KINDS}", name="ck_connections_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    secret_ref: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (
        CheckConstraint(f"status IN {SCAN_STATUSES}", name="ck_scans_status"),
        Index("ix_scans_created", text("created_at DESC"), "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), server_default="queued")
    sample_rows: Mapped[int] = mapped_column(Integer)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    score: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    finding_counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    assets_count: Mapped[int | None] = mapped_column(Integer)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report_version: Mapped[int | None] = mapped_column(Integer)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_scan_severity", "scan_id", "severity"),
        Index("ix_findings_check_type", "check_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"))
    check_type: Mapped[str] = mapped_column(String(100))
    asset: Mapped[str] = mapped_column(Text)
    column_name: Mapped[str | None] = mapped_column(Text)
    dimension: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    evaluated: Mapped[int] = mapped_column(BigInteger)
    failed: Mapped[int] = mapped_column(BigInteger)
    ratio: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    next_step: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
