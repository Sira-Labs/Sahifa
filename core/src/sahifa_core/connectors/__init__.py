"""Open a source from what the user typed: paths, a `duckdb://` URL or a `postgresql://` URL."""

from __future__ import annotations

from pathlib import Path

from ..errors import UsageError
from .base import Connector, Relation
from .duckdb import SUPPORTED_EXTENSIONS, DuckDBConnector, expand_paths
from .postgres import PostgresConnector

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "Connector",
    "DuckDBConnector",
    "PostgresConnector",
    "Relation",
    "open_source",
    "source_kind",
]


def source_kind(source: str) -> str:
    if source.startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
        return "postgres"
    return "duckdb"


def open_source(
    source: str | list[str],
    *,
    names: dict[str, str] | None = None,
    memory_limit: str = "1GB",
    statement_timeout_s: int = 60,
    application_name: str = "sahifa",
) -> Connector:
    """Open a read-only connector.

    `source` is one Postgres URL, one `duckdb:///path.duckdb` URL, or one or more paths to
    files, directories or globs. `names` maps a file path to the asset name to show (uploads
    keep their original names while being stored under random ones).
    """
    items = [source] if isinstance(source, str) else list(source)
    if not items:
        raise UsageError("no source given")
    first = items[0]
    if source_kind(first) == "postgres":
        if len(items) > 1:
            raise UsageError("scan one database at a time")
        return PostgresConnector(
            first, statement_timeout_s=statement_timeout_s, application_name=application_name
        )
    if first.startswith("duckdb://"):
        path = Path(first.removeprefix("duckdb://"))
        if not path.is_file():
            raise UsageError(f"no such DuckDB file: {path}")
        return DuckDBConnector(database=path, memory_limit=memory_limit)
    if len(items) == 1 and first.endswith(".duckdb") and Path(first).is_file():
        return DuckDBConnector(database=Path(first), memory_limit=memory_limit)
    return DuckDBConnector(files=expand_paths(items), names=names, memory_limit=memory_limit)
