"""Score history (spec 011).

- `scores`: one row per successful scan for the store (`asset_id` null) and one per table,
  with the overall score, its 95 % interval, the checks evaluated and the dimensions. Indexed
  for "the last N scans of a store" and "of a table".
- The upgrade fills it from the reports already stored. A report table with no asset row (a
  scan before spec 007 persisted assets) is skipped; nothing from the data is interpolated, the
  values are read from `scans.report` inside the database.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# Plain literals: the values are read from `scans.report` inside the database. `checks` is the
# sum over the score's dimensions.
BACKFILL_STORE = """
INSERT INTO scores (id, scan_id, connection_id, asset_id, measured_at, overall, low, high, checks, dimensions)
SELECT gen_random_uuid(), s.id, s.connection_id, NULL, s.finished_at,
       (s.report->'score'->>'overall')::float8,
       (s.report->'score'->>'low')::float8,
       (s.report->'score'->>'high')::float8,
       COALESCE((SELECT sum((d.value->>'checks')::int)
                 FROM jsonb_each(s.report->'score'->'dimensions') d), 0),
       COALESCE(s.report->'score'->'dimensions', '{}'::jsonb)
FROM scans s
WHERE s.status = 'succeeded' AND s.report IS NOT NULL AND s.finished_at IS NOT NULL
"""

BACKFILL_ASSETS = """
INSERT INTO scores (id, scan_id, connection_id, asset_id, measured_at, overall, low, high, checks, dimensions)
SELECT gen_random_uuid(), s.id, s.connection_id, a.id, s.finished_at,
       (r.value->'score'->>'overall')::float8,
       (r.value->'score'->>'low')::float8,
       (r.value->'score'->>'high')::float8,
       COALESCE((SELECT sum((d.value->>'checks')::int)
                 FROM jsonb_each(r.value->'score'->'dimensions') d), 0),
       COALESCE(r.value->'score'->'dimensions', '{}'::jsonb)
FROM scans s
CROSS JOIN LATERAL jsonb_array_elements(s.report->'assets') r
JOIN assets a
  ON a.connection_id = s.connection_id
 AND a.namespace = COALESCE(r.value->'ref'->>'namespace', '')
 AND a.name = r.value->'ref'->>'name'
WHERE s.status = 'succeeded' AND s.report IS NOT NULL AND s.finished_at IS NOT NULL
  AND jsonb_typeof(s.report->'assets') = 'array'
ON CONFLICT DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        "scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
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
            nullable=True,
        ),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("overall", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("checks", sa.Integer(), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "uq_scores_scan_store",
        "scores",
        ["scan_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NULL"),
    )
    op.create_index(
        "uq_scores_scan_asset",
        "scores",
        ["scan_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NOT NULL"),
    )
    op.create_index(
        "ix_scores_store_history",
        "scores",
        ["connection_id", sa.text("measured_at DESC")],
        postgresql_where=sa.text("asset_id IS NULL"),
    )
    op.create_index("ix_scores_asset_history", "scores", ["asset_id", sa.text("measured_at DESC")])
    op.execute(BACKFILL_STORE)
    op.execute(BACKFILL_ASSETS)


def downgrade() -> None:
    op.drop_index("ix_scores_asset_history", table_name="scores")
    op.drop_index("ix_scores_store_history", table_name="scores")
    op.drop_index("uq_scores_scan_asset", table_name="scores")
    op.drop_index("uq_scores_scan_store", table_name="scores")
    op.drop_table("scores")
