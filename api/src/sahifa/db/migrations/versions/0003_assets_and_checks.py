"""Assets, columns and checks persisted; lifecycle events (spec 007).

- `assets`: a table, view or file set per connection, upserted by each scan.
- `columns`: the asset's columns as the latest scan saw them.
- `checks`: one row per check of an asset, keyed by the core id; `status` follows the
  lifecycle of ADR-0005 and `version` guards changes by people and the scanner.
- `check_events`: who changed what; `actor` (email, `scanner`, `dev` or `proxy`) outlives the
  user, whose id is set null when the user is deleted.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "last_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('table', 'view', 'file')", name="ck_assets_kind"),
        sa.UniqueConstraint("connection_id", "namespace", "name", name="uq_assets_connection_namespace_name"),
    )
    op.create_table(
        "columns",
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("physical_type", sa.Text(), nullable=False),
        sa.Column("logical_type", sa.Text(), nullable=False),
        sa.Column("semantic_type", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
    )
    op.create_table(
        "checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=True),
        sa.Column("columns", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("params", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("dimension", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("max_fail_ratio", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "last_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'active', 'locked', 'retired')", name="ck_checks_status"),
        sa.CheckConstraint("kind IN ('rule', 'baseline', 'manual')", name="ck_checks_kind"),
        sa.CheckConstraint(
            "origin IN ('generated', 'manual', 'suggested', 'declared')", name="ck_checks_origin"
        ),
        sa.UniqueConstraint("asset_id", "key", name="uq_checks_asset_key"),
    )
    op.create_index("ix_checks_asset_status", "checks", ["asset_id", "status"])
    op.create_table(
        "check_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "check_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("checks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("params_before", postgresql.JSONB(), nullable=True),
        sa.Column("params_after", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "action IN ('created', 'regenerated', 'approve', 'reject', 'lock', 'unlock', 'retire', "
            "'restore')",
            name="ck_check_events_action",
        ),
    )
    op.create_index("ix_check_events_check_at", "check_events", ["check_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_check_events_check_at", table_name="check_events")
    op.drop_table("check_events")
    op.drop_index("ix_checks_asset_status", table_name="checks")
    op.drop_table("checks")
    op.drop_table("columns")
    op.drop_table("assets")
