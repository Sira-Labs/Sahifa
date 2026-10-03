"""Performance run (spec 013): the benchmark generator, the query budget, the examples cap,
the foreign-key check in linear time, and parallel scans equal to serial ones."""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import psycopg
import pytest

from sahifa_core import scan as scan_module
from sahifa_core.bench import create_schema, parse_mix
from sahifa_core.checks import BY_TYPE
from sahifa_core.errors import UsageError
from sahifa_core.models import ScanReport
from sahifa_core.scan import EXAMPLES_PER_ASSET, ScanOptions, run_scan

URL = os.environ.get("SAHIFA_TEST_SOURCE_URL")
needs_pg = pytest.mark.skipif(not URL, reason="SAHIFA_TEST_SOURCE_URL not set")

# Per asset: 3 metadata, 1 row count, 3 profile (aggregate, top values, MAD), 1 check
# aggregate, 1 newest timestamp.
FIXED_QUERIES = 9


def schema_url(schema: str) -> str:
    assert URL
    return f"{URL}{'&' if '?' in URL else '?'}schemas={schema}"


def test_parse_mix() -> None:
    assert [(t.tables, t.rows) for t in parse_mix("700x10000, 30x1000000")] == [
        (700, 10_000),
        (30, 1_000_000),
    ]
    for bad in ("", "x10", "10x", "0x5", "3x0", "3*5"):
        with pytest.raises(UsageError):
            parse_mix(bad)


def per_asset_queries(caplog: pytest.LogCaptureFixture) -> dict[str, int]:
    out = {}
    for rec in caplog.records:
        m = re.match(r"asset\.scanned (.+): [0-9.]+ s, (\d+) queries", rec.getMessage())
        if m:
            out[m[1]] = int(m[2])
    return out


def budget(report: ScanReport, label: str) -> int:
    results = next(a for a in report.assets if a.ref.label == label).checks
    fk = sum(1 for r in results if r.spec.type == "sah.foreign_key")
    python_columns = {r.spec.column for r in results if BY_TYPE[r.spec.type].evaluation == "python"}
    failing_sql = sum(1 for r in results if r.failed and BY_TYPE[r.spec.type].evaluation == "sql")
    return FIXED_QUERIES + fk + len(python_columns) + min(failing_sql, EXAMPLES_PER_ASSET)


def test_query_budget_per_asset(shop: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="sahifa_core.scan")
    report = run_scan(str(shop), ScanOptions(sample_rows=0))
    counts = per_asset_queries(caplog)
    assert set(counts) == {a.ref.label for a in report.assets}
    for label, n in counts.items():
        assert n <= budget(report, label), (label, n, budget(report, label))
    assert report.stats.queries_per_asset_max == max(counts.values())
    assert report.stats.queries_per_asset_mean == round(sum(counts.values()) / len(counts), 1)


def test_examples_are_capped_most_severe_first(shop: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scan_module, "EXAMPLES_PER_ASSET", 1)
    report = run_scan(str(shop), ScanOptions(sample_rows=0))
    order = list(scan_module.SEVERITY_ORDER)
    capped = 0
    for asset in report.assets:
        failing = [r for r in asset.checks if r.failed and BY_TYPE[r.spec.type].evaluation == "sql"]
        fetched = [r for r in failing if not r.examples_skipped]
        assert len(fetched) <= 1
        if len(failing) > 1:
            capped += 1
            skipped = [r for r in failing if r.examples_skipped]
            assert skipped and all(not r.examples for r in skipped)
            worst = min(order.index(r.spec.severity) for r in failing)
            assert order.index(fetched[0].spec.severity) == worst
    assert capped, "the shop should have an asset with more than one failing SQL check"
    flagged = [f for f in report.findings if f.examples_skipped]
    assert flagged and all(not f.examples for f in flagged)


# --- Postgres -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fk_schema() -> str:
    """A parent of 50,000 rows without any index and two children: one with an integer
    reference (compared natively), one with a text reference (compared as text)."""
    assert URL
    with psycopg.connect(URL, autocommit=True) as con:
        con.execute("DROP SCHEMA IF EXISTS sahifa_perf CASCADE")
        con.execute("CREATE SCHEMA sahifa_perf")
        con.execute(
            "CREATE TABLE sahifa_perf.customers AS SELECT g AS id, 'c' || g AS name "
            "FROM generate_series(1, 50000) g"
        )
        con.execute(
            "CREATE TABLE sahifa_perf.orders AS SELECT g AS id, "
            "CASE WHEN g % 500 = 0 THEN 60000 + g ELSE 1 + (g * 7) % 50000 END AS customer_id "
            "FROM generate_series(1, 20000) g"
        )
        con.execute(
            "CREATE TABLE sahifa_perf.invoices AS SELECT g AS id, "
            "CASE WHEN g % 400 = 0 THEN 'x' || g ELSE (1 + (g * 11) % 50000)::text END AS customer_id "
            "FROM generate_series(1, 20000) g"
        )
        con.execute("ANALYZE")
    return schema_url("sahifa_perf")


@needs_pg
def test_foreign_key_check_is_linear(fk_schema: str) -> None:
    t = time.monotonic()
    report = run_scan(fk_schema, ScanOptions(sample_rows=0, workers=1))
    elapsed = time.monotonic() - t
    assert elapsed < 20, f"the scan took {elapsed:.1f} s"
    fks = {
        r.spec.asset.name: (r.evaluated, r.failed)
        for a in report.assets
        for r in a.checks
        if r.spec.type == "sah.foreign_key"
    }
    # 20,000 rows each: every 500th order and every 400th invoice points nowhere.
    assert fks == {"orders": (20_000, 40), "invoices": (20_000, 50)}


def comparable(report: ScanReport) -> dict[str, Any]:
    data = report.model_dump(mode="json", exclude={"scan_id", "started_at", "finished_at", "stats"})
    return data


@needs_pg
def test_two_workers_give_the_serial_report(fk_schema: str) -> None:
    serial = run_scan(fk_schema, ScanOptions(sample_rows=5000, seed=3, workers=1), scan_id="s")
    parallel = run_scan(fk_schema, ScanOptions(sample_rows=5000, seed=3, workers=2), scan_id="s")
    assert serial.stats.workers == 1 and parallel.stats.workers == 2
    assert comparable(parallel) == comparable(serial)
    assert parallel.stats.queries == serial.stats.queries


@needs_pg
def test_bench_schema_refuses_a_schema_it_did_not_create() -> None:
    assert URL
    with psycopg.connect(URL, autocommit=True) as con:
        con.execute("DROP SCHEMA IF EXISTS sahifa_not_bench CASCADE")
        con.execute("CREATE SCHEMA sahifa_not_bench")
    with pytest.raises(UsageError, match="not a Sahifa benchmark schema"):
        create_schema(URL, schema="sahifa_not_bench", mix="1x10")
    assert create_schema(URL, schema="sahifa_bench_test", mix="2x50,1x200") == 4
    # Its own schema is replaced; 2,000 rows hold two orphans (every 997th row).
    assert create_schema(URL, schema="sahifa_bench_test", mix="1x2000") == 2
    report = run_scan(schema_url("sahifa_bench_test"), ScanOptions(sample_rows=0))
    assert {a.ref.name for a in report.assets} == {"customers", "t0000"}
    assert any(f.check_type == "sah.foreign_key" for f in report.findings)
    with psycopg.connect(URL, autocommit=True) as con:
        con.execute("DROP SCHEMA sahifa_not_bench CASCADE")
        con.execute("DROP SCHEMA sahifa_bench_test CASCADE")
