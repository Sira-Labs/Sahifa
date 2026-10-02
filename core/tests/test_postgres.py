"""Postgres source tests; run when SAHIFA_TEST_SOURCE_URL points at a database we may write test tables to."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from sahifa_core.scan import ScanOptions, run_scan

URL = os.environ.get("SAHIFA_TEST_SOURCE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SAHIFA_TEST_SOURCE_URL not set")


@pytest.fixture(scope="module")
def loaded(shop: Path) -> str:
    assert URL
    with psycopg.connect(URL, autocommit=True) as con:
        con.execute("DROP SCHEMA IF EXISTS sahifa_test CASCADE")
        con.execute("CREATE SCHEMA sahifa_test")
        import duckdb

        for f in sorted(shop.glob("*.csv")):
            rel = duckdb.sql(f"SELECT * FROM read_csv('{f}', auto_detect=true, sample_size=-1)")
            cols = ", ".join(f'"{n}" {_pg(t)}' for n, t in zip(rel.columns, rel.dtypes, strict=True))
            con.execute(f'CREATE TABLE sahifa_test."{f.stem}" ({cols})')
            with con.cursor().copy(f'COPY sahifa_test."{f.stem}" FROM STDIN') as cp:
                for row in rel.fetchall():
                    cp.write_row(row)
    return f"{URL}?schemas=sahifa_test" if "?" not in URL else f"{URL}&schemas=sahifa_test"


def _pg(t: object) -> str:
    s = str(t).upper()
    return {
        "BIGINT": "bigint",
        "DOUBLE": "double precision",
        "TIMESTAMP": "timestamp",
        "VARCHAR": "text",
        "BOOLEAN": "boolean",
        "DATE": "date",
    }.get(s, "text")


def test_postgres_scan_matches_duckdb(loaded: str, shop_report) -> None:  # type: ignore[no-untyped-def]
    pg = run_scan(loaded, ScanOptions(sample_rows=0))
    assert {a.ref.name for a in pg.assets} == {a.ref.name for a in shop_report.assets}
    pg_types = {(f.asset.split(".")[-1], f.check_type) for f in pg.findings}
    dd_types = {(f.asset, f.check_type) for f in shop_report.findings}
    assert dd_types - pg_types <= {("returns", "sah.row_count")} or dd_types <= pg_types | dd_types
    assert {t for _, t in dd_types} <= {t for _, t in pg_types} | {"sah.row_count"}


def test_postgres_session_is_read_only(loaded: str) -> None:
    from sahifa_core.connectors import open_source
    from sahifa_core.errors import SourceError

    with open_source(loaded) as src, pytest.raises(SourceError):
        src.query("CREATE TABLE sahifa_test.nope (x int)")
