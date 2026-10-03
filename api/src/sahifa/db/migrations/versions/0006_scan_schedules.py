"""Scan schedules and the scan's trigger (spec 010).

- `scan_schedules`: at most one per connection (deleted with it); a 5-field cron read in an
  IANA time zone, `next_run_at` in UTC (null while disabled), the last run and its outcome,
  and `version` guarding saves by people. The due-schedule job finds its rows through the
  index on (`enabled`, `next_run_at`).
- `scans.trigger`: `manual` (existing scans, and every scan a person starts) or `schedule`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scans", sa.Column("trigger", sa.String(20), server_default="manual", nullable=False))
    op.create_check_constraint("ck_scans_trigger", "scans", "trigger IN ('manual', 'schedule')")

    op.create_table(
        "scan_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cron", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), server_default="UTC", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sample_rows", sa.Integer(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_outcome", sa.String(20), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.UniqueConstraint("connection_id", name="uq_scan_schedules_connection_id"),
        sa.CheckConstraint(
            "last_outcome IN ('queued', 'skipped_running', 'failed_to_queue')",
            name="ck_scan_schedules_last_outcome",
        ),
    )
    op.create_index("ix_scan_schedules_enabled_next_run_at", "scan_schedules", ["enabled", "next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_scan_schedules_enabled_next_run_at", table_name="scan_schedules")
    op.drop_table("scan_schedules")
    op.drop_constraint("ck_scans_trigger", "scans", type_="check")
    op.drop_column("scans", "trigger")
