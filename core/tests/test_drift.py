"""Distribution shift (spec 026, check 16): the distances, and the check on the shop: the drift
twin's two shifted columns are reported with their effect size against locked baselines, and
clean data of the same and of another seed stays silent."""

from __future__ import annotations

import math
import random
from datetime import datetime
from pathlib import Path

import pytest

from sahifa_core import drift
from sahifa_core.checks import BY_TYPE
from sahifa_core.models import CheckResult, CheckSpec, CheckStatus, ScanReport
from sahifa_core.scan import ScanOptions, run_scan
from sahifa_core.synth import write_shop

SHIFT = "sah.distribution_shift"
ROWS = 5000

# --- The distances ---------------------------------------------------------------------------


def points(values: list[float]) -> list[tuple[float, float]]:
    """The seven points a profile would hold for these values."""
    ordered = sorted(values)

    def quantile(level: float) -> float:
        at = level * (len(ordered) - 1)
        low = math.floor(at)
        high = min(low + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (at - low)

    quantiles = {f"p{int(level * 100):02d}": quantile(level) for level in drift.LEVELS}
    return drift.points_of(ordered[0], quantiles, ordered[-1])


def test_points_and_distribution_function() -> None:
    p = drift.points_of(0, {"p01": 1, "p25": 25, "p50": 50, "p75": 75, "p99": 99}, 100)
    assert p[0] == (0.0, 0.0) and p[3] == (50.0, 0.5) and p[-1] == (100.0, 1.0)
    assert drift.cdf(p, -1) == 0.0 and drift.cdf(p, 100) == 1.0 and drift.cdf(p, 1000) == 1.0
    assert drift.cdf(p, 50) == 0.5 and drift.cdf(p, 62.5) == pytest.approx(0.625)
    assert drift.cdf_inverse(p, 0.5) == 50.0
    # Equal values at several levels: the highest level counts.
    flat = drift.points_of(5, {"p01": 5, "p25": 5, "p50": 5, "p75": 9, "p99": 9}, 9)
    assert drift.cdf(flat, 5) == pytest.approx(0.5) and drift.cdf(flat, 9) == 1.0


def test_ks_distance_of_a_location_shift() -> None:
    reference = points([float(i) for i in range(1000)])
    assert drift.ks_distance(reference, reference) == 0.0
    shifted = points([float(i) + 250 for i in range(1000)])
    assert drift.ks_distance(reference, shifted) == pytest.approx(0.25, abs=0.01)
    assert drift.ks_distance(shifted, reference) == pytest.approx(0.25, abs=0.01)
    apart = points([float(i) + 5000 for i in range(1000)])
    assert drift.ks_distance(reference, apart) == 1.0


def test_ks_distance_sees_a_change_of_spread() -> None:
    rng = random.Random(1)
    narrow = points([rng.gauss(0, 1) for _ in range(20_000)])
    wide = points([rng.gauss(0, 2) for _ in range(20_000)])
    assert drift.ks_distance(narrow, wide) > drift.MIN_EFFECT


def test_ks_critical_value_shrinks_with_the_samples() -> None:
    assert drift.ks_critical(2, 2) == pytest.approx(1.95, abs=0.005)
    assert drift.ks_critical(100, 100) == pytest.approx(0.276, abs=0.001)
    assert drift.ks_critical(100_000, 100_000) < 0.01


def test_wasserstein_in_interquartile_ranges() -> None:
    reference = points([float(i) for i in range(1001)])
    assert drift.wasserstein_in_iqr(reference, reference) == 0.0
    shifted = points([float(i) + 250 for i in range(1001)])
    assert drift.wasserstein_in_iqr(reference, shifted) == pytest.approx(0.5)  # 250 of an IQR of 500
    constant = drift.points_of(3, dict.fromkeys(("p01", "p25", "p50", "p75", "p99"), 3.0), 3)
    assert drift.wasserstein_in_iqr(constant, shifted) is None
    assert drift.wasserstein_in_iqr(reference, [(0.0, 0.0), (1.0, 1.0)]) is None


def test_bins_keep_the_baseline_values_and_collect_new_ones() -> None:
    bins = drift.bins_of({"a": 50, "b": 50}, {"a": 40, "c": 10, "d": 5}, 55)
    assert bins == [("a", 50, 40), ("b", 50, 0), (drift.OTHER, 0, 15)]
    assert drift.bins_of({"a": 5, "b": 5}, {"a": 7, "b": 3}, 10) == [("a", 5, 7), ("b", 5, 3)]


def test_distances_between_value_mixes() -> None:
    same = [("a", 500, 50), ("b", 500, 50)]
    assert drift.total_variation(same) == 0.0 and drift.js_distance(same) == 0.0
    assert drift.psi(same) == pytest.approx(0.0, abs=1e-3)
    moved = [("a", 500, 300), ("b", 500, 700)]
    assert drift.total_variation(moved) == pytest.approx(0.2)
    assert drift.js_distance(moved) == pytest.approx(0.1741, abs=1e-3)
    assert drift.psi(moved) == pytest.approx(0.2 * math.log(0.7 / 0.5) - 0.2 * math.log(0.3 / 0.5), abs=1e-3)
    disjoint = [("a", 10, 0), ("b", 0, 10)]
    assert drift.js_distance(disjoint) == pytest.approx(1.0)
    assert math.isfinite(drift.psi(disjoint))


def test_chi_square_quantile_and_psi_critical_value() -> None:
    # Exact quantiles at 0.999: 10.83, 13.82, 27.88, 45.31.
    for df, exact in ((1, 10.83), (2, 13.82), (9, 27.88), (20, 45.31)):
        assert drift.chi_square_quantile(df) == pytest.approx(exact, rel=0.035)
    assert drift.psi_critical(3, 500, 500) == pytest.approx(drift.chi_square_quantile(2) * 0.004)
    assert drift.psi_critical(3, 100_000, 100_000) < 0.001  # why an effect size has to decide


def test_same_distribution_stays_below_the_thresholds() -> None:
    """Two samples of one distribution: neither the numbers nor the mix are called shifted."""
    rng = random.Random(11)
    alarms = 0
    for _ in range(300):
        n = rng.choice([100, 300, 1000, 5000])
        a = points([rng.lognormvariate(3, 1) for _ in range(n)])
        b = points([rng.lognormvariate(3, 1) for _ in range(n)])
        alarms += drift.ks_distance(a, b) >= max(drift.MIN_EFFECT, drift.ks_critical(n, n))
        ref = {v: 0 for v in "abcdefghij"}
        cur = dict(ref)
        for _ in range(n):
            ref[rng.choice("abcdefghij")] += 1
            cur[rng.choice("abcdefghij")] += 1
        bins = drift.bins_of(ref, cur, n)
        alarms += drift.js_distance(bins) >= drift.MIN_EFFECT and drift.psi(bins) >= drift.psi_critical(
            len(bins), n, n
        )
    assert alarms <= 3  # 600 comparisons at one in a thousand each, with room for the estimate


# --- The check on the shop -------------------------------------------------------------------


def locked(report: ScanReport) -> dict[str, list[CheckSpec]]:
    """Every proposed distribution baseline of a scan, approved."""
    saved: dict[str, list[CheckSpec]] = {}
    for spec in report.checks:
        if spec.type == SHIFT:
            saved.setdefault(spec.asset.label, []).append(
                spec.model_copy(update={"status": CheckStatus.LOCKED})
            )
    return saved


def shifts(report: ScanReport) -> dict[tuple[str, str | None], CheckResult]:
    return {
        (r.spec.asset.label, r.spec.column): r
        for a in report.assets
        for r in a.checks
        if r.spec.type == SHIFT
    }


@pytest.fixture(scope="module")
def baselines(clean_report: ScanReport) -> dict[str, list[CheckSpec]]:
    return locked(clean_report)


@pytest.fixture(scope="module")
def drift_report(
    tmp_path_factory: pytest.TempPathFactory, baselines: dict[str, list[CheckSpec]], shop_now: datetime
) -> ScanReport:
    d = tmp_path_factory.mktemp("drift")
    write_shop(d, rows=ROWS, drift=True, now=shop_now)
    return run_scan(str(d), ScanOptions(sample_rows=0, now=shop_now), saved=baselines)


def test_baselines_are_proposed_for_numbers_and_few_values(clean_report: ScanReport) -> None:
    specs = {(s.asset.label, s.column): s for s in clean_report.checks if s.type == SHIFT}
    assert specs[("events", "payload_size")].params["form"] == "numeric"
    assert len(specs[("events", "payload_size")].params["points"]) == 7
    assert specs[("events", "kind")].params["form"] == "values"
    assert set(specs[("events", "kind")].params["counts"]) == {"view", "cart", "checkout"}
    assert sum(specs[("events", "kind")].params["counts"].values()) == ROWS // 2
    assert all(s.status == CheckStatus.PROPOSED and s.kind == "baseline" for s in specs.values())
    # Keys, timestamps, free text and personal data have no distribution baseline.
    columns = {column for _asset, column in specs}
    assert not columns & {"id", "customer_id", "occurred_at", "ordered_at", "name", "email", "iban"}
    assert all("measured" not in s.params for s in specs.values())
    assert BY_TYPE[SHIFT].release == "R2"


def test_shifted_mix_is_reported_with_its_effect_size(drift_report: ScanReport) -> None:
    finding = next(f for f in drift_report.findings if f.check_type == SHIFT and f.column == "kind")
    result = shifts(drift_report)[("events", "kind")]
    measured = result.spec.params["measured"]
    assert measured["distance"] >= drift.MIN_EFFECT and measured["psi"] > measured["psi_critical"]
    # Half of the views became checkouts: exactly those rows are counted.
    views = result.spec.params["counts"]["view"]
    assert finding.failed == views // 2 and finding.evaluated == ROWS // 2
    assert measured["changed"] == pytest.approx(finding.failed / finding.evaluated, abs=1e-4)
    assert f"Jensen–Shannon distance {measured['distance']:.2f}" in finding.summary
    assert f"PSI {measured['psi']:.3f}" in finding.summary and "critical value" in finding.summary
    assert finding.next_step and finding.severity.value == "medium"
    assert [e.value.split(":")[0] for e in finding.examples[:2]] == ["checkout", "view"]  # type: ignore[union-attr]
    assert "→" in (finding.examples[0].value or "")


def test_shifted_numbers_are_reported_with_their_effect_size(drift_report: ScanReport) -> None:
    finding = next(f for f in drift_report.findings if f.check_type == SHIFT and f.column == "payload_size")
    measured = shifts(drift_report)[("events", "payload_size")].spec.params["measured"]
    # Half of the lower half moved up: a quarter of the rows crossed the old median.
    assert measured["distance"] == pytest.approx(0.25, abs=0.03)
    assert measured["threshold"] == drift.MIN_EFFECT
    assert measured["moved_iqr"] > 0.1 and measured["median"][1] > measured["median"][0]
    assert finding.failed == math.ceil(measured["distance"] * finding.evaluated)
    assert f"Kolmogorov–Smirnov distance {measured['distance']:.2f}" in finding.summary
    assert (
        "interquartile ranges (Wasserstein)" in finding.summary and "the median went from" in finding.summary
    )


def test_only_the_shifted_columns_are_reported(drift_report: ScanReport) -> None:
    found = {(f.asset, f.column) for f in drift_report.findings if f.check_type == SHIFT}
    assert found == {("events", "kind"), ("events", "payload_size")}
    # 20 orders with a status never seen and 10 negative amounts are other checks' findings.
    others = shifts(drift_report)
    assert others[("orders", "status")].passed and others[("orders", "amount")].passed
    assert "matches its baseline" in others[("orders", "status")].summary
    assert "match their baseline" in others[("orders", "amount")].summary


def test_clean_twin_stays_silent(
    clean_shop: Path, baselines: dict[str, list[CheckSpec]], shop_now: datetime
) -> None:
    report = run_scan(str(clean_shop), ScanOptions(sample_rows=0, now=shop_now), saved=baselines)
    results = shifts(report)
    assert len(results) >= 8
    assert all(r.passed and r.failed == 0 for r in results.values())
    assert all(r.spec.params["measured"]["distance"] == 0 for r in results.values())
    assert report.findings == []


def test_new_clean_data_stays_silent(
    tmp_path: Path, baselines: dict[str, list[CheckSpec]], shop_now: datetime
) -> None:
    """Another draw of the same shop, also read through a sample: no finding."""
    write_shop(tmp_path, rows=ROWS, clean=True, seed=1234, now=shop_now)
    for sample_rows in (0, 1000):
        report = run_scan(str(tmp_path), ScanOptions(sample_rows=sample_rows, now=shop_now), saved=baselines)
        assert not [f for f in report.findings if f.check_type == SHIFT], sample_rows


def test_column_that_lost_its_numbers_is_not_compared(
    tmp_path: Path, baselines: dict[str, list[CheckSpec]], shop_now: datetime
) -> None:
    write_shop(tmp_path, rows=ROWS, clean=True, now=shop_now)
    events = tmp_path / "events.csv"
    lines = events.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    at = header.index("payload_size")
    rows = [line.split(",") for line in lines[1:]]
    for row in rows:
        row[at] = f"size {row[at]}"
    events.write_text("\n".join([lines[0], *(",".join(r) for r in rows)]) + "\n", encoding="utf-8")
    report = run_scan(str(tmp_path), ScanOptions(sample_rows=0, now=shop_now), saved=baselines)
    result = shifts(report)[("events", "payload_size")]
    assert (result.evaluated, result.failed, result.passed) == (0, 0, True)
    assert "could not be compared" in result.summary
