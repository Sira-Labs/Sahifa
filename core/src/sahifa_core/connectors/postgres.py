"""Postgres connector: read-only sessions with timeouts (ADR-0006)."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg

from ..errors import SourceError
from ..models import AssetInfo, AssetRef, ColumnInfo, ForeignKey, LogicalType
from ..sql import PostgresDialect
from .base import Connector, Relation

# Above this planner estimate the population is not counted exactly (count(*) is a full scan).
EXACT_COUNT_LIMIT = 10_000_000
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")

_TYPES: dict[str, LogicalType] = {
    "smallint": LogicalType.INTEGER,
    "integer": LogicalType.INTEGER,
    "bigint": LogicalType.INTEGER,
    "numeric": LogicalType.DECIMAL,
    "real": LogicalType.DECIMAL,
    "double precision": LogicalType.DECIMAL,
    "money": LogicalType.DECIMAL,
    "boolean": LogicalType.BOOLEAN,
    "character varying": LogicalType.TEXT,
    "character": LogicalType.TEXT,
    "text": LogicalType.TEXT,
    "uuid": LogicalType.TEXT,
    "name": LogicalType.TEXT,
    "citext": LogicalType.TEXT,
    "date": LogicalType.DATE,
    "timestamp without time zone": LogicalType.TIMESTAMP,
    "timestamp with time zone": LogicalType.TIMESTAMP,
    "json": LogicalType.JSON,
    "jsonb": LogicalType.JSON,
    "bytea": LogicalType.BINARY,
}


def logical_type(data_type: str, udt_name: str) -> LogicalType:
    if data_type == "USER-DEFINED" and udt_name == "citext":
        return LogicalType.TEXT
    return _TYPES.get(data_type, LogicalType.OTHER)


def split_url(url: str) -> tuple[str, list[str]]:
    """Remove Sahifa's own `schemas=` parameter; return the libpq URL and the schema list."""
    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)
    schemas = [s.strip() for k, v in params if k == "schemas" for s in v.split(",") if s.strip()]
    rest = [(k, v) for k, v in params if k != "schemas"]
    scheme = (
        "postgresql" if parts.scheme in ("postgres", "postgresql", "postgresql+psycopg") else parts.scheme
    )
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(rest), parts.fragment)), schemas


def redact(message: str, url: str) -> str:
    """Remove the password of `url` from an error message, whatever the driver put in it."""
    password = urlsplit(url).password
    if password:
        message = message.replace(password, "***")
    return re.sub(r"\s+", " ", message).strip()[:500]


class PostgresConnector(Connector):
    kind: Literal["duckdb", "postgres"] = "postgres"

    def __init__(self, url: str, *, statement_timeout_s: int = 60, application_name: str = "sahifa") -> None:
        super().__init__()
        self.dialect = PostgresDialect()
        self._url, self.schemas = split_url(url)
        parts = urlsplit(self._url)
        self.label = f"{parts.hostname or 'localhost'}/{parts.path.lstrip('/') or 'postgres'}"
        options = " ".join(
            [
                "-c default_transaction_read_only=on",
                f"-c statement_timeout={int(statement_timeout_s) * 1000}",
                "-c lock_timeout=2000",
                "-c idle_in_transaction_session_timeout=300000",
                "-c TimeZone=UTC",
                "-c standard_conforming_strings=on",
            ]
        )
        try:
            self.con = psycopg.connect(
                self._url, options=options, application_name=application_name[:63], connect_timeout=10
            )
            self.con.read_only = True
            self.con.autocommit = True
        except psycopg.Error as e:
            raise SourceError(f"cannot connect: {redact(str(e), url)}") from e

    def _schema_filter(self) -> tuple[str, list[Any]]:
        if self.schemas:
            return "n.nspname = ANY(%s)", [self.schemas]
        return "n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg\\_%%'", [list(SYSTEM_SCHEMAS)]

    def _params(self, sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
        self.queries += 1
        try:
            with self.con.cursor() as cur:
                cur.execute(sql.encode(), params)  # metadata queries use bound parameters
                return cur.fetchall()
        except psycopg.Error as e:
            raise SourceError(redact(str(e), self._url)) from e

    def list_assets(self) -> list[AssetRef]:
        where, params = self._schema_filter()
        rows = self._params(
            "SELECT n.nspname, c.relname, c.relkind FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE c.relkind IN ('r', 'p', 'v', 'm') AND NOT c.relispartition AND {where} "
            "AND has_table_privilege(c.oid, 'SELECT') ORDER BY 1, 2",
            params,
        )
        return [AssetRef(namespace=s, name=n, kind="view" if k == "v" else "table") for s, n, k in rows]

    def describe(self, ref: AssetRef) -> AssetInfo:
        cols = self._params(
            "SELECT column_name, data_type, udt_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            [ref.namespace, ref.name],
        )
        if not cols:
            raise SourceError(f"{ref.label} has no readable columns")
        columns = [
            ColumnInfo(
                name=n,
                position=i + 1,
                physical_type=udt if dt in ("USER-DEFINED", "ARRAY") else dt,
                logical_type=logical_type(dt, udt),
                declared_not_null=(nullable == "NO"),
            )
            for i, (n, dt, udt, nullable) in enumerate(cols)
        ]
        info = AssetInfo(ref=ref, columns=columns)
        cons = self._params(
            "SELECT c.contype, "
            "array(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(n, o) "
            "  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n ORDER BY k.o)::text[], "
            "fn.nspname, fc.relname, "
            "array(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(n, o) "
            "  JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.n ORDER BY k.o)::text[] "
            "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "LEFT JOIN pg_class fc ON fc.oid = c.confrelid "
            "LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace "
            "WHERE n.nspname = %s AND t.relname = %s AND c.contype IN ('p', 'u', 'f') ORDER BY c.conname",
            [ref.namespace, ref.name],
        )
        for contype, keys, fschema, ftable, fkeys in cons:
            keys = list(keys or [])
            if contype == "p":
                info.primary_key = keys
            elif contype == "u":
                info.unique.append(keys)
            elif contype == "f" and len(keys) == 1 and fkeys:
                info.foreign_keys.append(
                    ForeignKey(
                        column=keys[0],
                        parent=AssetRef(namespace=fschema, name=ftable),
                        parent_column=next(iter(fkeys)),
                    )
                )
        est = self._params(
            "SELECT c.reltuples::bigint FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s",
            [ref.namespace, ref.name],
        )
        info.row_estimate = int(est[0][0]) if est and est[0][0] is not None and est[0][0] >= 0 else None
        return info

    def count_rows(self, ref: AssetRef, info: AssetInfo) -> tuple[int, bool]:
        if info.row_estimate is not None and info.row_estimate > EXACT_COUNT_LIMIT:
            return info.row_estimate, False
        rows = self.query(f"SELECT count(*) FROM {self.dialect.table(ref)}")
        return int(rows[0][0]), True

    def sample(self, ref: AssetRef, rows: int, seed: int, population: int) -> Relation:
        full = self.dialect.table(ref)
        name = self.dialect.ident("_sahifa_sample")
        if rows <= 0 or population <= rows:
            body, method = f"SELECT * FROM {full}", "full"
        elif ref.kind == "view":
            # TABLESAMPLE needs a table; a view gives its first rows, and the report says so.
            body, method = f"SELECT * FROM {full} LIMIT {int(rows)}", f"first {rows:,} rows of a view"
        else:
            # Over-sample by a fifth so LIMIT almost always has enough rows to take.
            pct = min(100.0, 100.0 * rows * 1.2 / max(population, 1))
            body = (
                f"SELECT * FROM {full} TABLESAMPLE BERNOULLI ({pct:.6f}) REPEATABLE ({int(seed)}) "
                f"LIMIT {int(rows)}"
            )
            method = f"Bernoulli sample of about {rows:,} rows (seed {seed})"
        return Relation(asset=ref, ref=name, full=full, prefix=f"WITH {name} AS ({body}) ", method=method)

    def _execute(self, sql: str) -> list[tuple[Any, ...]]:
        try:
            with self.con.cursor() as cur:
                cur.execute(sql.encode())
                return cur.fetchall() if cur.description else []
        except psycopg.Error as e:
            raise SourceError(redact(str(e), self._url)) from e

    def close(self) -> None:
        self.con.close()
