"""Measure history per column (spec 024).

- `column_measures`: one row per scan, table and column with the profile's measures as
  `{name: number}`, the rows read, the table's rows and whether the profile was sampled.
- Workspace-owned through its table (migration 0008): the workspace is filled by trigger and
  the table is under forced row-level security.
- Rows go with their scan, table and connection (cascades).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TABLE = "column_measures"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rows", sa.BigInteger(), nullable=False),
        sa.Column("population", sa.BigInteger(), nullable=True),
        sa.Column("sampled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("measures", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_column_measures_workspace_id", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "scan_id", "asset_id", "column_name", name="uq_column_measures_scan_asset_column"
        ),
    )
    op.create_index("ix_column_measures_workspace_id", TABLE, ["workspace_id"])
    op.create_index("ix_column_measures_scan_id", TABLE, ["scan_id"])
    op.create_index("ix_column_measures_connection_id", TABLE, ["connection_id"])
    op.create_index(
        "ix_column_measures_history", TABLE, ["asset_id", "column_name", sa.text("measured_at DESC")]
    )
    op.execute(
        f"CREATE TRIGGER trg_{TABLE}_workspace BEFORE INSERT ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION sahifa_fill_workspace('assets', 'asset_id')"
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY workspace_isolation ON {TABLE} "
        "USING (sahifa_visible(workspace_id)) WITH CHECK (sahifa_visible(workspace_id))"
    )


def downgrade() -> None:
    op.drop_table(TABLE)
