"""Accuracy benchmark (spec 014): the shop's fault list matches its files, every R1 check has a
fault, and a small run detects every fault on a full read and stays silent on the clean twin."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sahifa_core import accuracy
from sahifa_core.accuracy import R1_CHECKS, AccuracyReport, render_markdown, run_benchmark
from sahifa_core.checks import BY_TYPE
from sahifa_core.cli import main
from sahifa_core.synth import MIN_DRIFT_ROWS, shop_tables

NOW = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)

Rows = dict[str, list[dict[str, str]]]


def read_csv(directory: Path) -> Rows:
    out = {}
    for path in sorted(directory.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            out[path.stem] = list(csv.DictReader(f))
    return out


def stamp(v: str) -> datetime:
    return datetime.strptime(v, "%Y-%m-%d %H:%M:%S")


def number(v: str) -> float | None:
    try:
        return float(v)
    except ValueError:
        return None


def recount_faulty(t: Rows, check: str, asset: str, column: str | None) -> int:
    """The fault counted directly on the CSV text, where a missing value is an empty cell."""
    rows = t[asset]
    vals = [r[column] for r in rows] if column else []
    if check == "sah.row_count":
        return int(not rows)
    if check == "sah.duplicate_rows":
        return len(rows) - len({tuple(r.values()) for r in rows})
    if check == "sah.unique":
        return len(vals) - len(set(vals))
    if check == "sah.column_order":
        return sum(1 for r in rows if stamp(r["shipped_at"]) < stamp(r["ordered_at"]))
    counters: dict[str, Callable[[str], bool]] = {
        "sah.not_null": lambda v: v == "",
        "sah.not_blank": lambda v: v.strip().lower() == "n/a",
        "sah.whitespace": lambda v: v != "" and v != v.strip(),
        "sah.non_printing": lambda v: "​" in v,
        "sah.future_dates": lambda v: v != "" and stamp(v) > NOW.replace(tzinfo=None),
        "sah.implausible_dates": lambda v: v != "" and stamp(v).year < 1900,
        "sah.type_conformance": lambda v: number(v) is None,
        "sah.outliers": lambda v: (number(v) or 0) > 1000,
    }
    if check in counters:
        return sum(1 for v in vals if counters[check](v))
    if check == "sah.semantic_format":
        shape = {"email": r"[^@\s]+@[^@\s]+\.\w+", "iban": r"DE\d{20}", "vat_id": r"DE\d{9}"}[column or ""]
        ok = [v for v in vals if v != "" and re.fullmatch(shape, v)]
        if column == "iban":
            ok = [v for v in ok if int("".join(str(int(c, 36)) for c in v[4:] + v[:4])) % 97 == 1]
        return sum(1 for v in vals if v != "") - len(ok)
    if check == "sah.casing_variants":
        groups: dict[str, Counter[str]] = {}
        for v in vals:
            groups.setdefault(v.strip().lower(), Counter())[v] += 1
        return sum(sum(c.values()) - c.most_common(1)[0][1] for c in groups.values())
    if check == "sah.foreign_key":
        parent = {"customer_id": "customers", "product_id": "products", "order_id": "orders"}[column or ""]
        keys = {r["id"] for r in t[parent]}
        return sum(1 for v in vals if v != "" and v not in keys)
    raise AssertionError(f"no recount for {check}")


def recount_drift(t: Rows, clean: Rows, check: str, asset: str, column: str | None) -> int:
    if check == "sah.freshness":
        newest = max(stamp(r["occurred_at"]) for r in t[asset])
        return int(newest < max(stamp(r["occurred_at"]) for r in clean[asset]))
    vals, before = [r[column or ""] for r in t[asset]], [r[column or ""] for r in clean[asset]]
    if check == "sah.accepted_values":
        seen = set(before)
        return sum(1 for v in vals if v not in seen)
    if check == "sah.pattern":
        return sum(1 for v in vals if not re.fullmatch(r"SKU-\d{5}", v))
    if check == "sah.length":
        longest = max(len(b) for b in before)
        return sum(1 for v in vals if len(v) > longest)
    if check == "sah.range" and column == "amount":
        lowest = min(float(b) for b in before)
        return sum(1 for v in vals if float(v) < lowest)
    if check == "sah.range":
        first = min(stamp(b) for b in before)
        return sum(1 for v in vals if stamp(v) < first)
    raise AssertionError(f"no recount for {check}")


def test_fault_list_counts_match_the_files(tmp_path: Path) -> None:
    faulty = shop_tables(rows=MIN_DRIFT_ROWS, seed=3, now=NOW)
    drift = shop_tables(drift=True, rows=MIN_DRIFT_ROWS, seed=3, now=NOW)
    clean = shop_tables(clean=True, rows=MIN_DRIFT_ROWS, seed=3, now=NOW)
    for name, shop in (("faulty", faulty), ("drift", drift), ("clean", clean)):
        shop.write(tmp_path / name)
    files = {name: read_csv(tmp_path / name) for name in ("faulty", "drift", "clean")}
    assert clean.faults == []
    for f in faulty.faults:
        assert recount_faulty(files["faulty"], f.check, f.asset, f.column) == f.rows, f
    for f in drift.faults:
        assert recount_drift(files["drift"], files["clean"], f.check, f.asset, f.column) == f.rows, f


def test_every_r1_check_has_a_fault() -> None:
    rules = {t for t in R1_CHECKS if BY_TYPE[t].kind == "rule"}
    baselines = {t for t in R1_CHECKS if BY_TYPE[t].kind == "baseline"}
    assert len(rules) == 15 and len(baselines) == 5
    assert {f.check for f in shop_tables(rows=MIN_DRIFT_ROWS, now=NOW).faults} == rules
    assert {f.check for f in shop_tables(drift=True, rows=MIN_DRIFT_ROWS, now=NOW).faults} == baselines


def test_benchmark_small_run() -> None:
    report = run_benchmark(seeds=2, rows=MIN_DRIFT_ROWS, sample_rows=300)
    by_check = report.by_check()
    assert set(by_check) == set(R1_CHECKS)
    for m in report.checks:
        assert m.groups >= 2, m
        assert m.detected == m.groups, f"{m.check} missed {m.groups - m.detected} of {m.groups} fault groups"
        assert m.unexpected == 0, m
        if m.kind == "rule":
            assert (m.clean_findings, m.clean_failed_rows) == (0, 0), m
            assert m.sampled_groups == m.groups
        else:
            assert m.baseline_checks > 0, m
    table = render_markdown(report).splitlines()
    assert len(table) == 2 + len(R1_CHECKS)
    assert all(f"`{t}`" in "\n".join(table) for t in R1_CHECKS)


def test_bench_accuracy_cli_passes_options_and_prints_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []

    def fake(**kwargs: Any) -> AccuracyReport:
        calls.append(kwargs)
        return AccuracyReport(kwargs["seeds"], kwargs["rows"], kwargs["sample_rows"], "now")

    monkeypatch.setattr(accuracy, "run_benchmark", fake)
    assert main(["bench-accuracy", "--seeds", "3", "--rows", "4000", "--sample-rows", "200", "--json"]) == 0
    assert {k: calls[0][k] for k in ("seeds", "rows", "sample_rows")} == {
        "seeds": 3,
        "rows": 4000,
        "sample_rows": 200,
    }
    assert json.loads(capsys.readouterr().out)["seeds"] == 3


@pytest.mark.parametrize(
    "args",
    [["--seeds", "0"], ["--rows", str(MIN_DRIFT_ROWS - 1)], ["--sample-rows", "0"], ["--seeds", "x"]],
)
def test_bench_accuracy_cli_rejects_bad_options(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bench-accuracy", *args]) == 2
