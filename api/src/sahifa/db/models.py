"""Tables of migrations 0001 (spec 004), 0002 (spec 006), 0003 (spec 007), 0004 (spec 008), 0005
(spec 009), 0006 (spec 010) and 0007 (spec 011).

Procrastinate's own tables (migration 0004) are not mapped here; Alembic ignores them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base

CONNECTION_KINDS = ("postgres", "duckdb", "upload")
SCAN_STATUSES = ("queued", "running", "succeeded", "failed")
SCAN_TRIGGERS = ("manual", "schedule")
SCHEDULE_OUTCOMES = ("queued", "skipped_running", "failed_to_queue", "invalid_schedule")
SIGN_IN_METHODS = ("google", "github", "passkey")
ASSET_KINDS = ("table", "view", "file")
CHECK_KINDS = ("rule", "baseline", "manual")
CHECK_ORIGINS = ("generated", "manual", "suggested", "declared")
CHECK_STATUSES = ("proposed", "active", "locked", "retired")
CHECK_ACTIONS = ("created", "regenerated", "approve", "reject", "lock", "unlock", "retire", "restore")
FINDING_STATUSES = ("open", "acknowledged", "resolved", "muted")
# The scanner's actions (past tense), then people's (imperative), as for check events.
FINDING_ACTIONS = (
    "opened",
    "recurred",
    "auto_resolved",
    "reopened",
    "unmuted",
    "acknowledge",
    "resolve",
    "mute",
    "unmute",
    "reopen",
)
NOTE_MAX = 1000


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
        CheckConstraint(f"trigger IN {SCAN_TRIGGERS}", name="ck_scans_trigger"),
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
    # The Procrastinate job that runs the scan in queue mode (spec 008); no foreign key, since
    # Procrastinate owns its table and may delete finished jobs.
    job_id: Mapped[int | None] = mapped_column(BigInteger)
    # Who started it: a person (`manual`) or the connection's schedule (spec 010).
    trigger: Mapped[str] = mapped_column(String(20), server_default="manual")


class ScanSchedule(Base):
    """A connection's schedule (spec 010): a 5-field cron read in an IANA time zone.

    `next_run_at` (UTC) is null while the schedule is disabled. `version` grows by one on every
    save by a person; the due-schedule job only moves `next_run_at` and the `last_*` columns."""

    __tablename__ = "scan_schedules"
    __table_args__ = (
        UniqueConstraint("connection_id", name="uq_scan_schedules_connection_id"),
        CheckConstraint(f"last_outcome IN {SCHEDULE_OUTCOMES}", name="ck_scan_schedules_last_outcome"),
        Index("ix_scan_schedules_enabled_next_run_at", "enabled", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"))
    cron: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Null: the `SAHIFA_SAMPLE_ROWS` default at the time of each run.
    sample_rows: Mapped[int | None] = mapped_column(Integer)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    last_outcome: Mapped[str | None] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Who saved it last: the email, `dev` or `proxy` (spec 007's actor).
    updated_by: Mapped[str] = mapped_column(Text)


class FindingOccurrence(Base):
    """One failing check in one scan, with its evidence (spec 004's per-scan findings, renamed by
    spec 009). `finding_id` links it to the finding across scans; null before migration 0005."""

    __tablename__ = "finding_occurrences"
    __table_args__ = (
        Index("ix_finding_occurrences_scan_severity", "scan_id", "severity"),
        Index("ix_finding_occurrences_check_type", "check_type"),
        Index("ix_finding_occurrences_finding_scan", "finding_id", "scan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"))
    finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"))
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


class User(Base):
    """A person who signed in through the realm (spec 006): one identity (issuer, subject).

    Access is not stored: it follows `SAHIFA_ADMIN_EMAIL` and `SAHIFA_ALLOWED_EMAILS` at each
    request, so editing the setting takes effect at the next restart.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
        CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    issuer: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    """A signed-in browser (spec 006); the cookie holds a token, the table only its HMAC."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(f"sign_in_method IN {SIGN_IN_METHODS}", name="ck_sessions_sign_in_method"),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_idp_sid", "idp_sid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    sign_in_method: Mapped[str] = mapped_column(String(20))
    idp_sid: Mapped[str | None] = mapped_column(Text)
    id_token: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginFlow(Base):
    """A sign-in between `/api/auth/login` and the callback (10 minutes, single use)."""

    __tablename__ = "login_flows"

    id_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    state: Mapped[str] = mapped_column(Text)
    nonce: Mapped[str] = mapped_column(Text)
    code_verifier: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(20))
    next_path: Mapped[str] = mapped_column("next", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Asset(Base):
    """A table, view or file set of a connection, as the latest scan saw it (spec 007)."""

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("connection_id", "namespace", "name", name="uq_assets_connection_namespace_name"),
        CheckConstraint(f"kind IN {ASSET_KINDS}", name="ck_assets_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"))
    namespace: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    last_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def label(self) -> str:
        """`namespace.name`, or the name alone; the core's `AssetRef.label`."""
        from sahifa_core.models import label_of

        return label_of(self.namespace, self.name)


class AssetColumn(Base):
    """A column of an asset; each scan replaces the asset's set."""

    __tablename__ = "columns"

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    physical_type: Mapped[str] = mapped_column(Text)
    logical_type: Mapped[str] = mapped_column(Text)
    semantic_type: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)


class Check(Base):
    """A check of an asset with its lifecycle status (ADR-0005); `key` is the core's `CheckSpec.id`.

    `version` grows by one on every change, by a person or the scanner, and guards both
    against lost updates."""

    __tablename__ = "checks"
    __table_args__ = (
        UniqueConstraint("asset_id", "key", name="uq_checks_asset_key"),
        CheckConstraint(f"status IN {CHECK_STATUSES}", name="ck_checks_status"),
        CheckConstraint(f"kind IN {CHECK_KINDS}", name="ck_checks_kind"),
        CheckConstraint(f"origin IN {CHECK_ORIGINS}", name="ck_checks_origin"),
        Index("ix_checks_asset_status", "asset_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(100))
    column_name: Mapped[str | None] = mapped_column(Text)
    columns: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    dimension: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    max_fail_ratio: Mapped[float] = mapped_column(Float, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    last_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CheckEvent(Base):
    """One change of a check: created or regenerated by the scanner (no user), or a person's action.

    Rows are only ever inserted; `actor` keeps who it was after the user is deleted."""

    __tablename__ = "check_events"
    __table_args__ = (
        CheckConstraint(f"action IN {CHECK_ACTIONS}", name="ck_check_events_action"),
        Index("ix_check_events_check_at", "check_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    check_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Who, as text that outlives the user row: the email at the time, `scanner`, `dev` or `proxy`.
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(20))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    params_before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    params_after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Finding(Base):
    """A failing check across scans (spec 009): at most one per check that is not resolved.

    `version` grows by one on every change, by a person or the scanner, like a check's."""

    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint(f"status IN {FINDING_STATUSES}", name="ck_findings_status"),
        Index(
            "uq_findings_check_unresolved",
            "check_id",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
        ),
        Index("ix_findings_check_id", "check_id"),
        Index("ix_findings_status_severity", "status", "severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    check_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(20))
    occurrences: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    first_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    last_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FindingEvent(Base):
    """One change of a finding: by the scanner (no user) or a person's action, with a note.

    Rows are only ever inserted; `actor` keeps who it was after the user is deleted."""

    __tablename__ = "finding_events"
    __table_args__ = (
        CheckConstraint(f"action IN {FINDING_ACTIONS}", name="ck_finding_events_action"),
        CheckConstraint(f"char_length(note) <= {NOTE_MAX}", name="ck_finding_events_note_length"),
        Index("ix_finding_events_finding_at", "finding_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Who, as text that outlives the user row: the email at the time, `scanner`, `dev` or `proxy`.
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(20))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)


class ScoreRecord(Base):
    """A scan's score at one level (spec 011): the store (`asset_id` null) or one table.

    One row per level rather than per dimension: the history reads whole points, and a
    1,000-table scan writes 1,001 rows instead of seven times that. `connection_id` and
    `measured_at` (the scan's `finished_at`) are copied from the scan so that a history is one
    index range."""

    __tablename__ = "scores"
    __table_args__ = (
        Index("uq_scores_scan_store", "scan_id", unique=True, postgresql_where=text("asset_id IS NULL")),
        Index(
            "uq_scores_scan_asset",
            "scan_id",
            "asset_id",
            unique=True,
            postgresql_where=text("asset_id IS NOT NULL"),
        ),
        Index(
            "ix_scores_store_history",
            "connection_id",
            text("measured_at DESC"),
            postgresql_where=text("asset_id IS NULL"),
        ),
        Index("ix_scores_asset_history", "asset_id", text("measured_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 0-100; null when the level had nothing to evaluate.
    overall: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    checks: Mapped[int] = mapped_column(Integer)
    # {dimension: {value, low, high, checks}}, as in the report's `Score.dimensions`.
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB)
