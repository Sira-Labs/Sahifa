"""A wide Postgres schema for the performance run (spec 013): many tables of mixed sizes with
a realistic column mix, a declared foreign key and a few faults, generated server-side.

This writes, so it only ever targets a benchmark database the operator names, never a source:
it creates one schema, and replaces it only when that schema carries this module's marker.
Each table it creates carries the marker too, and replacement drops only those tables.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from .errors import UsageError
from .sql import PostgresDialect

MARKER = "sahifa benchmark schema"
DEFAULT_MIX = "700x10000,270x100000,30x1000000"
PARENT_ROWS = 100_000


@dataclass(frozen=True)
class Tier:
    tables: int
    rows: int


def parse_mix(text: str) -> list[Tier]:
    """`700x10000,30x1000000` as tiers of (tables, rows)."""
    tiers = []
    for part in text.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*", part)
        if not m:
            raise UsageError(f"mix entry {part!r} is not TABLESxROWS")
        tiers.append(Tier(tables=int(m[1]), rows=int(m[2])))
    if not tiers or any(t.tables < 1 or t.rows < 1 for t in tiers):
        raise UsageError("the mix needs at least one tier of at least one table and row")
    return tiers


def child_table_sql(table: str, parent: str, rows: int) -> str:
    """One child table: ten columns of the common types, with nulls, a duplicated value, an
    out-of-range amount and orphans of the parent every so often."""
    return f"""
CREATE TABLE {table} AS SELECT
  g AS id,
  CASE WHEN g % 997 = 0 THEN {PARENT_ROWS} + g ELSE 1 + (g::bigint * 7919) % {PARENT_ROWS} END AS customer_id,
  CASE WHEN g % 50 = 0 THEN NULL ELSE 'user' || (g % 5000) || '@example.org' END AS email,
  CASE WHEN g % 1009 = 0 THEN -1 ELSE round((random() * 1000)::numeric, 2) END AS amount,
  (ARRAY['new', 'paid', 'shipped', 'returned'])[1 + g % 4] AS status,
  (ARRAY['DE', 'CH', 'AT', 'FR', 'IT', 'NL'])[1 + g % 6] AS country,
  timestamptz '2026-01-01' + (g % 400000) * interval '1 minute' AS created_at,
  (g % 3 = 0) AS flag,
  CASE WHEN g % 10 = 0 THEN NULL ELSE md5(g::text) END AS note,
  g % 1000 AS bucket
FROM generate_series(1, {rows}) AS g"""


def create_schema(
    url: str,
    *,
    schema: str = "bench",
    mix: str = DEFAULT_MIX,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Create the benchmark schema in the database at `url`; returns the number of tables."""
    d = PostgresDialect()
    tiers = parse_mix(mix)
    s = d.ident(schema)
    say = progress or (lambda _m: None)
    with psycopg.connect(url, autocommit=True) as con:
        existing = con.execute(
            "SELECT obj_description(n.oid, 'pg_namespace') FROM pg_namespace n WHERE n.nspname = %s", [schema]
        ).fetchone()
        if existing is not None:
            if existing[0] != MARKER:
                raise UsageError(f"schema {schema!r} exists and is not a Sahifa benchmark schema; refusing")
            _drop_schema(con, schema)
        con.execute(f"CREATE SCHEMA {s}".encode())
        con.execute(f"COMMENT ON SCHEMA {s} IS {d.literal(MARKER)}".encode())
        parent = f"{s}.{d.ident('customers')}"
        con.execute(
            f"CREATE TABLE {parent} AS SELECT g AS id, 'user' || g || '@example.org' AS email "
            f"FROM generate_series(1, {PARENT_ROWS}) AS g".encode()
        )
        con.execute(f"ALTER TABLE {parent} ADD PRIMARY KEY (id)".encode())
        con.execute(f"COMMENT ON TABLE {parent} IS {d.literal(MARKER)}".encode())
        tables = [parent]
        n = 0
        started = time.monotonic()
        for tier in tiers:
            for _ in range(tier.tables):
                table = f"{s}.{d.ident(f't{n:04d}')}"
                con.execute(child_table_sql(table, parent, tier.rows).encode())
                con.execute(f"ALTER TABLE {table} ADD PRIMARY KEY (id)".encode())
                # NOT VALID keeps the orphans, as in a legacy database whose constraint came late.
                fk = f"ALTER TABLE {table} ADD FOREIGN KEY (customer_id) REFERENCES {parent} (id) NOT VALID"
                con.execute(fk.encode())
                con.execute(f"COMMENT ON TABLE {table} IS {d.literal(MARKER)}".encode())
                tables.append(table)
                n += 1
                if n % 50 == 0:
                    say(f"{n} tables, {time.monotonic() - started:.0f} s")
        # Only the generated tables: a bare ANALYZE would also reach every other schema.
        con.execute(f"ANALYZE {', '.join(tables)}".encode())
    return n + 1


def _drop_schema(con: psycopg.Connection[tuple[object, ...]], schema: str) -> None:
    """Drop a marked benchmark schema without CASCADE: the tables this module created (marked
    like the schema) in one restrictive statement, so the foreign keys among them go with them,
    then the empty schema, in one transaction. An object elsewhere that depends on a benchmark
    table (a view in another schema), or anything left in the schema that this module did not
    create, makes it refuse and keep everything as it was."""
    d = PostgresDialect()
    s = d.ident(schema)
    names = [
        str(r[0])
        for r in con.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('r', 'p') "
            "AND obj_description(c.oid, 'pg_class') = %s ORDER BY c.relname",
            [schema, MARKER],
        )
    ]
    try:
        with con.transaction():
            if names:
                tables = ", ".join(f"{s}.{d.ident(name)}" for name in names)
                con.execute(f"DROP TABLE {tables} RESTRICT".encode())
            con.execute(f"DROP SCHEMA {s} RESTRICT".encode())
    except psycopg.errors.DependentObjectsStillExist as e:
        raise UsageError(
            f"benchmark schema {schema!r} has objects that depend on it or that it did not create; "
            f"refusing to drop it ({e.diag.message_primary})"
        ) from e
