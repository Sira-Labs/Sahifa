"""Procrastinate job queue and `scans.job_id` (spec 008, ADR-0009).

- The Procrastinate 3.10.0 schema (`0004_procrastinate_3_10_0.sql` next to this file): its
  tables, types, functions and triggers, all named `procrastinate_*`. The Alembic environment
  ignores them, so `alembic check` stays clean.
- `scans.job_id`: the Procrastinate job that runs the scan in queue mode.

The downgrade drops every `procrastinate_*` object in the schema.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SCHEMA_SQL = Path(__file__).with_name("0004_procrastinate_3_10_0.sql")

# Tables first (their triggers and row types go with them), then the functions and the enum
# and composite types left over, found by name in the current schema.
DROP_PROCRASTINATE = """
DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs,
    procrastinate_workers CASCADE;
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT p.oid::regprocedure AS signature
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = current_schema() AND left(p.proname, 14) = 'procrastinate_'
    LOOP
        EXECUTE 'DROP FUNCTION ' || r.signature::text;
    END LOOP;
    FOR r IN
        SELECT t.typname
          FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE n.nspname = current_schema() AND left(t.typname, 14) = 'procrastinate_'
           AND (t.typtype = 'e' OR (t.typtype = 'c' AND t.typrelid IN
                (SELECT c.oid FROM pg_class c WHERE c.relkind = 'c')))
    LOOP
        EXECUTE format('DROP TYPE %I', r.typname);
    END LOOP;
END;
$$;
"""


def upgrade() -> None:
    op.execute(sa.text(SCHEMA_SQL.read_text(encoding="utf-8")))
    op.add_column("scans", sa.Column("job_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("scans", "job_id")
    op.execute(sa.text(DROP_PROCRASTINATE))
