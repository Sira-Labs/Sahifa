"""Hostile names and values never break out of their SQL position (spec 002)."""

from __future__ import annotations

import csv

from sahifa_core.scan import ScanOptions, run_scan
from sahifa_core.sql import DuckDBDialect, PostgresDialect

HOSTILE = "x'); DROP TABLE t; --"


def test_literals_and_identifiers_are_escaped() -> None:
    for d in (DuckDBDialect(), PostgresDialect()):
        assert d.literal(HOSTILE) == "'x''); DROP TABLE t; --'"
        assert d.ident('a"b') == '"a""b"'


def test_scan_survives_hostile_names(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "evil.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", HOSTILE, 'quote"col'])
        for i in range(60):
            w.writerow([i, HOSTILE if i % 2 else "ok", "a"])
    report = run_scan(str(path), ScanOptions(sample_rows=0))
    assert report.assets[0].error is None
    assert {c.profile.name for c in report.assets[0].columns} == {"id", HOSTILE, 'quote"col'}
