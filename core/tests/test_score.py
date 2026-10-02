from __future__ import annotations

import math

from sahifa_core.score import Estimate, check_interval, product, weighted_mean


def test_full_read_has_zero_width() -> None:
    p, lo, hi = check_interval(1000, 10, 1000)
    assert p == lo == hi == 0.99


def test_sample_interval_contains_share_and_shrinks_with_n() -> None:
    p, lo, hi = check_interval(1000, 10, 100_000)
    assert lo < p < hi
    _, lo2, hi2 = check_interval(10_000, 100, 100_000)
    assert (hi2 - lo2) < (hi - lo)


def test_finite_population_correction_narrows() -> None:
    _, lo_inf, hi_inf = check_interval(1000, 10, 10**9)
    _, lo_fpc, hi_fpc = check_interval(1000, 10, 2000)
    assert (hi_fpc - lo_fpc) < (hi_inf - lo_inf)


def test_product_weights_by_severity() -> None:
    low_sev = product([(0.5, 0.0, 0.1)])
    critical = product([(0.5, 0.0, 1.0)])
    assert low_sev and critical
    assert math.isclose(low_sev.value, 0.5**0.1) and math.isclose(critical.value, 0.5)


def test_weighted_mean_variance() -> None:
    m = weighted_mean([(Estimate(1.0, 0.0), 1.0), (Estimate(0.0, 0.04), 1.0)])
    assert m and math.isclose(m.value, 0.5) and math.isclose(m.var, 0.01)


def test_scores_are_bounded(shop_report) -> None:  # type: ignore[no-untyped-def]
    for d in shop_report.score.dimensions.values():
        assert 0 <= d.low <= d.value <= d.high <= 100


def test_sampled_scan_has_intervals(shop) -> None:  # type: ignore[no-untyped-def]
    from sahifa_core.scan import ScanOptions, run_scan

    r = run_scan(str(shop), ScanOptions(sample_rows=500, seed=3))
    assert any(d.low < d.high for d in r.score.dimensions.values())
