"""Procrastinate 3.12.0, first half: lock modes, a retry that fails instead of raising, lock index.

Procrastinate 3.12.0 ships five migration scripts. The three "pre" scripts, applied here as
released (`0013_procrastinate_3_12_0_pre_*.sql` next to this file), must be in place before
its code runs, and the functions they install still serve 3.11.0, so the schema may be ahead
of the running code during a deploy:

1. `lock_mode` on jobs, the type `procrastinate_job_to_defer_v2`, `procrastinate_defer_jobs_v2`
   and `procrastinate_defer_periodic_job_v3`; `procrastinate_fetch_job_v2` honours the mode.
2. `procrastinate_retry_job_v2` fails a running job whose retry meets a queueing lock.
3. The index `procrastinate_jobs_todo_doing_lock_idx_v1`, built concurrently, hence outside
   the migration's transaction. Should the build fail, drop the invalid index
   (`DROP INDEX CONCURRENTLY procrastinate_jobs_todo_doing_lock_idx_v1`) and migrate again.

The two "post" scripts drop what 3.11.0 still calls (`procrastinate_defer_jobs_v1`, its type,
the index on (id, lock)). They belong in a later migration, released after this one, so that
no api or worker of the previous release is left when they run.

The downgrade puts back the functions of 3.11.0, read from the scripts migrations 0004 and
0011 applied, and removes what the scripts added.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-23
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

VERSIONS = Path(__file__).parent
TRANSACTIONAL_SQL = (
    VERSIONS / "0013_procrastinate_3_12_0_pre_01.sql",
    VERSIONS / "0013_procrastinate_3_12_0_pre_02.sql",
)
CONCURRENT_INDEX_SQL = VERSIONS / "0013_procrastinate_3_12_0_pre_03.sql"
SCHEMA_3_10_SQL = VERSIONS / "0004_procrastinate_3_10_0.sql"
FETCH_JOB_3_11_SQL = VERSIONS / "0011_procrastinate_3_11_0.sql"

FUNCTION_END = "\n$$;"

DROP_ADDITIONS_SQL = """
DROP FUNCTION procrastinate_defer_periodic_job_v3(
    character varying, character varying, procrastinate_lock_mode, character varying,
    character varying, integer, character varying, bigint, jsonb
);
DROP FUNCTION procrastinate_defer_jobs_v2(procrastinate_job_to_defer_v2[]);
DROP TYPE procrastinate_job_to_defer_v2;
ALTER TABLE procrastinate_jobs DROP COLUMN lock_mode;
DROP TYPE procrastinate_lock_mode;
"""


def statement(script: Path) -> str:
    """The one statement of a script, without its comments: it must run on its own."""
    lines = script.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith("--")).strip()


def function_of(script: Path, name: str) -> str:
    """`CREATE OR REPLACE FUNCTION <name>` as the given released script defines it."""
    text = script.read_text(encoding="utf-8")
    start = min(
        at
        for head in (f"CREATE FUNCTION {name}(", f"CREATE OR REPLACE FUNCTION {name}(")
        if (at := text.find(head)) >= 0
    )
    end = text.index(FUNCTION_END, start) + len(FUNCTION_END)
    body = text[text.index("FUNCTION", start) : end]
    return f"CREATE OR REPLACE {body}"


def upgrade() -> None:
    for script in TRANSACTIONAL_SQL:
        op.execute(sa.text(script.read_text(encoding="utf-8")))
    with op.get_context().autocommit_block():
        op.execute(sa.text(statement(CONCURRENT_INDEX_SQL)))


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS procrastinate_jobs_todo_doing_lock_idx_v1"))
    op.execute(sa.text(function_of(FETCH_JOB_3_11_SQL, "procrastinate_fetch_job_v2")))
    op.execute(sa.text(function_of(SCHEMA_3_10_SQL, "procrastinate_retry_job_v2")))
    op.execute(sa.text(function_of(SCHEMA_3_10_SQL, "procrastinate_defer_periodic_job_v2")))
    op.execute(sa.text(DROP_ADDITIONS_SQL))
