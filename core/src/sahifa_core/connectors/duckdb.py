"""DuckDB connector: uploaded and local files, and `.duckdb` databases (ADR-0002)."""

from __future__ import annotations

import contextlib
import glob
import re
from pathlib import Path
from typing import Any, Literal

import duckdb

from ..errors import SourceError, UsageError
from ..models import AssetInfo, AssetRef, ColumnInfo, ForeignKey, LogicalType
from ..sql import DuckDBDialect
from .base import Connector, Relation

FILE_READERS: dict[str, str] = {
    ".csv": "read_csv",
    ".tsv": "read_csv",
    ".txt": "read_csv",
    ".parquet": "read_parquet",
    ".json": "read_json_auto",
    ".jsonl": "read_json_auto",
    ".ndjson": "read_json_auto",
}
SUPPORTED_EXTENSIONS = frozenset(FILE_READERS)


def logical_type(physical: str) -> LogicalType:
    """Map a DuckDB type name to the logical type the checks reason about."""
    t = physical.upper()
    if t.endswith("[]") or t.startswith(("STRUCT", "MAP", "UNION")) or "[" in t:
        return LogicalType.OTHER
    if t in {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
        "INT",
        "INT8",
        "INT4",
        "INT2",
    }:
        return LogicalType.INTEGER
    if t in {"FLOAT", "DOUBLE", "REAL"} or t.startswith(("DECIMAL", "NUMERIC")):
        return LogicalType.DECIMAL
    if t == "BOOLEAN":
        return LogicalType.BOOLEAN
    if t in {"VARCHAR", "UUID", "TEXT", "STRING"} or t.startswith(("VARCHAR", "ENUM")):
        return LogicalType.TEXT
    if t == "DATE":
        return LogicalType.DATE
    if t.startswith("TIMESTAMP") or t == "DATETIME":
        return LogicalType.TIMESTAMP
    if t == "JSON":
        return LogicalType.JSON
    if t in {"BLOB", "BYTEA", "BIT"}:
        return LogicalType.BINARY
    return LogicalType.OTHER


def expand_paths(paths: list[str]) -> list[Path]:
    """Files named directly, every supported file in a named directory, or a glob's matches."""
    files: list[Path] = []
    for raw in paths:
        if raw.startswith(("s3://", "gs://", "http://", "https://")):
            raise UsageError(f"remote paths are not supported yet (spec 009): {raw}")
        p = Path(raw).expanduser()
        if any(ch in raw for ch in "*?["):
            files.extend(
                sorted(
                    Path(m)
                    for m in glob.glob(str(p))
                    if Path(m).is_file() and Path(m).suffix.lower() in SUPPORTED_EXTENSIONS
                )
            )
        elif p.is_dir():
            files.extend(
                sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() in SUPPORTED_EXTENSIONS)
            )
        elif p.is_file():
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                raise UsageError(f"unsupported file type {p.suffix!r}: {p.name}")
            files.append(p)
        else:
            raise UsageError(f"no such file or directory: {raw}")
    if not files:
        raise UsageError("no CSV, Parquet or JSON files found")
    return files


class DuckDBConnector(Connector):
    """One in-memory DuckDB per scan, with a view per file, or a read-only `.duckdb` file."""

    kind: Literal["duckdb", "postgres"] = "duckdb"

    def __init__(
        self,
        files: list[Path] | None = None,
        database: Path | None = None,
        *,
        names: dict[str, str] | None = None,
        memory_limit: str = "1GB",
        threads: int = 2,
    ) -> None:
        super().__init__()
        self.dialect = DuckDBDialect()
        self._views: dict[str, AssetRef] = {}
        self._counter = 0
        try:
            if database is not None:
                self.con = duckdb.connect(str(database), read_only=True)
                self.label = database.name
            else:
                self.con = duckdb.connect(":memory:")
                self.label = ", ".join(f.name for f in (files or [])[:3]) + (
                    f" and {len(files or []) - 3} more" if len(files or []) > 3 else ""
                )
            self.con.execute(f"SET memory_limit = {self.dialect.literal(memory_limit)}")
            self.con.execute(f"SET threads = {int(threads)}")
            # Without ICU, timestamps with time zone stay in local time.
            with contextlib.suppress(duckdb.Error):
                self.con.execute("SET TimeZone = 'UTC'")
        except duckdb.Error as e:
            raise SourceError(f"cannot open DuckDB: {e}") from e
        self._database = database
        if files:
            self._register_files(files, names or {})

    def _register_files(self, files: list[Path], names: dict[str, str]) -> None:
        used: set[str] = set()
        for f in files:
            stem = names.get(str(f), f.stem)
            name = stem if stem not in used else f"{stem}_{f.suffix.lstrip('.')}"
            used.add(name)
            reader = FILE_READERS[f.suffix.lower()]
            path = self.dialect.literal(str(f.resolve()))
            if reader == "read_csv":
                # sample_size=-1: detect types on every row, so a late "N/A" makes the column
                # text instead of failing the scan halfway through.
                delim = ", delim = '\t'" if f.suffix.lower() == ".tsv" else ""
                source = f"read_csv({path}, auto_detect = true, sample_size = -1{delim})"
            else:
                source = f"{reader}({path})"
            ref = AssetRef(name=name, kind="file")
            try:
                self.con.execute(f"CREATE VIEW {self.dialect.ident(name)} AS SELECT * FROM {source}")
            except duckdb.Error as e:
                raise SourceError(f"cannot read {f.name}: {e}") from e
            self._views[name] = ref

    def list_assets(self) -> list[AssetRef]:
        if self._database is None:
            return list(self._views.values())
        rows = self.query(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1, 2"
        )
        return [
            AssetRef(namespace="" if s == "main" else s, name=n, kind="view" if t == "VIEW" else "table")
            for s, n, t in rows
        ]

    def full_ref(self, ref: AssetRef) -> str:
        return self._from(ref)

    def _from(self, ref: AssetRef) -> str:
        if ref.namespace:
            return self.dialect.table(ref)
        return self.dialect.ident(ref.name)

    def describe(self, ref: AssetRef) -> AssetInfo:
        try:
            rows = self.query(f"DESCRIBE SELECT * FROM {self._from(ref)}")
        except duckdb.Error as e:
            raise SourceError(f"cannot describe {ref.label}: {e}") from e
        columns = [
            ColumnInfo(
                name=r[0], position=i + 1, physical_type=str(r[1]), logical_type=logical_type(str(r[1]))
            )
            for i, r in enumerate(rows)
        ]
        info = AssetInfo(ref=ref, columns=columns)
        if self._database is not None and ref.kind == "table":
            self._declared_constraints(info)
        return info

    def _declared_constraints(self, info: AssetInfo) -> None:
        schema = info.ref.namespace or "main"
        rows = self.query(
            "SELECT constraint_type, constraint_column_names, referenced_table, referenced_column_names "
            "FROM duckdb_constraints() WHERE schema_name = "
            f"{self.dialect.literal(schema)} AND table_name = {self.dialect.literal(info.ref.name)}"
        )
        not_null: set[str] = set()
        for ctype, cols, ref_table, ref_cols in rows:
            cols = list(cols or [])
            if ctype == "PRIMARY KEY":
                info.primary_key = cols
                not_null.update(cols)
            elif ctype == "UNIQUE":
                info.unique.append(cols)
            elif ctype == "NOT NULL":
                not_null.update(cols)
            elif ctype == "FOREIGN KEY" and len(cols) == 1 and ref_table and ref_cols:
                info.foreign_keys.append(
                    ForeignKey(
                        column=cols[0],
                        parent=AssetRef(namespace=info.ref.namespace, name=ref_table),
                        parent_column=next(iter(ref_cols)),
                    )
                )
        for c in info.columns:
            c.declared_not_null = c.name in not_null

    def count_rows(self, ref: AssetRef, info: AssetInfo) -> tuple[int, bool]:
        rows = self.query(f"SELECT count(*) FROM {self._from(ref)}")
        return int(rows[0][0]), True

    def sample(self, ref: AssetRef, rows: int, seed: int, population: int) -> Relation:
        self._counter += 1
        name = self.dialect.ident(f"_sahifa_sample_{self._counter}")
        full = self._from(ref)
        if rows <= 0 or population <= rows:
            body, method = f"SELECT * FROM {full}", "full"
        else:
            body = f"SELECT * FROM {full} USING SAMPLE reservoir({int(rows)} ROWS) REPEATABLE ({int(seed)})"
            method = f"reservoir sample of {rows:,} rows (seed {seed})"
        try:
            self.query(f"CREATE TEMP TABLE {name} AS {body}")
        except duckdb.Error as e:
            raise SourceError(f"cannot read {ref.label}: {e}") from e
        return Relation(asset=ref, ref=name, full=full, method=method)

    def release(self, relation: Relation) -> None:
        self.con.execute(f"DROP TABLE IF EXISTS {relation.ref}")

    def _execute(self, sql: str) -> list[tuple[Any, ...]]:
        try:
            return self.con.execute(sql).fetchall()
        except duckdb.Error as e:
            raise SourceError(_clean(str(e))) from e

    def close(self) -> None:
        self.con.close()


def _clean(message: str) -> str:
    return re.sub(r"\s+", " ", message).strip()[:500]
