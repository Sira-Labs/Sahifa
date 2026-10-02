"""Scores with 95 % intervals (ADR-0004, docs/architecture/02-domain-model.md "Scoring (v1)").

Every score is the pass share of what was evaluated. Intervals cover sampling uncertainty only:
the Wilson interval with the finite-population correction per check, the delta method for the
weighted geometric product within a column, and variance propagation for weighted means above.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .models import Dimension, DimensionScore, Role, Score

Z = 1.959964
ROLE_WEIGHT = {
    Role.KEY: 3.0,
    Role.FOREIGN_KEY: 2.5,
    Role.TIMESTAMP: 2.0,
    Role.MEASURE: 1.5,
    Role.ATTRIBUTE: 1.0,
    Role.DESCRIPTION: 0.5,
}


@dataclass(frozen=True)
class Estimate:
    """A share in [0, 1] with the variance of its estimate."""

    value: float
    var: float
    checks: int = 1

    @property
    def low(self) -> float:
        return max(0.0, self.value - Z * math.sqrt(self.var))

    @property
    def high(self) -> float:
        return min(1.0, self.value + Z * math.sqrt(self.var))


def check_interval(n: int, k: int, population: int) -> tuple[float, float, float]:
    """Pass share and 95 % Wilson interval; zero width when every item was read."""
    if n <= 0:
        return 1.0, 1.0, 1.0
    p = (n - k) / n
    if population <= n or n == 1:
        return p, p, p
    n_eff = n * (population - 1) / (population - n)
    denom = 1 + Z * Z / n_eff
    centre = (p + Z * Z / (2 * n_eff)) / denom
    half = Z * math.sqrt(p * (1 - p) / n_eff + Z * Z / (4 * n_eff * n_eff)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def variance_of(low: float, high: float) -> float:
    return ((high - low) / (2 * Z)) ** 2


def product(items: Iterable[tuple[float, float, float]]) -> Estimate | None:
    """Weighted geometric product of (share, variance, weight); delta method on the log."""
    items = list(items)
    if not items:
        return None
    log_s, var_log = 0.0, 0.0
    for p, var, w in items:
        p = max(p, 1e-9)
        log_s += w * math.log(p)
        var_log += w * w * var / (p * p)
    s = math.exp(log_s)
    return Estimate(s, s * s * var_log, len(items))


def weighted_mean(items: Iterable[tuple[Estimate, float]]) -> Estimate | None:
    items = [(e, w) for e, w in items if w > 0]
    if not items:
        return None
    total = sum(w for _, w in items)
    value = sum(e.value * w for e, w in items) / total
    var = sum(w * w * e.var for e, w in items) / (total * total)
    return Estimate(value, var, sum(e.checks for e, _ in items))


def to_score(dims: dict[Dimension, Estimate]) -> Score:
    if not dims:
        return Score(overall=None, low=None, high=None)
    overall = Estimate(
        sum(e.value for e in dims.values()) / len(dims),
        sum(e.var for e in dims.values()) / len(dims) ** 2,
        sum(e.checks for e in dims.values()),
    )
    return Score(
        overall=_pct(overall.value),
        low=_pct(overall.low),
        high=_pct(overall.high),
        dimensions={
            d: DimensionScore(value=_pct(e.value), low=_pct(e.low), high=_pct(e.high), checks=e.checks)
            for d, e in sorted(dims.items(), key=lambda kv: list(Dimension).index(kv[0]))
        },
    )


def _pct(v: float) -> float:
    return round(100 * min(1.0, max(0.0, v)), 1)


def asset_weight(rows: int) -> float:
    return 1 + math.log10(1 + max(rows, 0))
