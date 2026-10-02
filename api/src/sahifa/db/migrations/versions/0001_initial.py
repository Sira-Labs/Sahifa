"""Initial schema: connections, scans, findings (spec 004).

Revision ID: 0001
Revises:
Create Date: 2026-10-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("secret_ref", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('postgres', 'duckdb', 'upload')", name="ck_connections_kind"),
        sa.UniqueConstraint("name", name="connections_name_key"),
    )
    op.create_table(
        "scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("sample_rows", sa.Integer(), nullable=False),
        sa.Column("options", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("score", postgresql.JSONB(), nullable=True),
        sa.Column("finding_counts", postgresql.JSONB(), nullable=True),
        sa.Column("assets_count", sa.Integer(), nullable=True),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("report_version", sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_scans_status"),
    )
    op.create_index("ix_scans_created", "scans", [sa.text("created_at DESC"), "id"])
    op.create_table(
        "findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("check_type", sa.String(100), nullable=False),
        sa.Column("asset", sa.Text(), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=True),
        sa.Column("dimension", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("evaluated", sa.BigInteger(), nullable=False),
        sa.Column("failed", sa.BigInteger(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("next_step", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index("ix_findings_scan_severity", "findings", ["scan_id", "severity"])
    op.create_index("ix_findings_check_type", "findings", ["check_type"])


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_table("scans")
    op.drop_table("connections")
