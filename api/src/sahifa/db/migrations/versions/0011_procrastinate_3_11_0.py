"""Procrastinate 3.11.0: `procrastinate_fetch_job_v2` skips the lock check for jobs without a lock.

Procrastinate 3.11.0 changes one function of its schema and nothing else: a job without a lock
is accepted before the subquery over the other jobs is considered, so Postgres no longer plans
a scan of every job for each of them. Its script (`0011_procrastinate_3_11_0.sql` next to this
file, as released) is a "pre" migration: the function it installs also serves 3.10.0, so the
schema may be ahead of the running code during a deploy.

The downgrade puts back the function of 3.10.0, read from the schema migration 0004 applied.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-17
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

MIGRATION_SQL = Path(__file__).with_name("0011_procrastinate_3_11_0.sql")
SCHEMA_3_10_SQL = Path(__file__).with_name("0004_procrastinate_3_10_0.sql")

FUNCTION_HEAD = "CREATE FUNCTION procrastinate_fetch_job_v2("
FUNCTION_END = "\n$$;"


def fetch_job_3_10() -> str:
    """`CREATE OR REPLACE` of `procrastinate_fetch_job_v2` as Procrastinate 3.10.0 defined it."""
    schema = SCHEMA_3_10_SQL.read_text(encoding="utf-8")
    start = schema.index(FUNCTION_HEAD)
    end = schema.index(FUNCTION_END, start) + len(FUNCTION_END)
    return "CREATE OR REPLACE" + schema[start + len("CREATE") : end]


def upgrade() -> None:
    op.execute(sa.text(MIGRATION_SQL.read_text(encoding="utf-8")))


def downgrade() -> None:
    op.execute(sa.text(fetch_job_3_10()))
