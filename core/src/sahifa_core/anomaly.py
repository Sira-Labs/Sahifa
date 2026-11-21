"""Anomaly thresholds on the history of a measure (spec 025, catalogue check 17).

A measure (a column's null share, its mean, a table's row count) is read once per scan. The
question for the newest reading is whether it is unusual given the ones before. The answer has
two parts:

- a **baseline**: what the next reading is expected to be: the median of the last readings,
  or, for a regular schedule with a cycle (a weekly load), the median of the readings at the
  same position in the last cycles;
- a **conformal interval** around it: the baseline's own past errors, one-step-ahead, give the
  width at which only a chosen share of ordinary readings falls outside (the false-alarm
  rate). No distribution is assumed.

Everything here is pure arithmetic on a list of numbers; storing and reading the history is the
caller's.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

# One ordinary reading in twenty is reported as unusual.
DEFAULT_RATE = 0.05
# Readings the level is the median of: enough to shrug off one outlier, few enough to follow
# a level that moves.
WINDOW = 10
# Readings before the first forecast is made.
WARM_UP = 3
# Cycles a seasonal forecast reads, and the cycles that must be complete before the first one.
CYCLES = 4
CYCLES_BEFORE = 2
# Width below which two readings count as equal (floating-point noise), relative to the level.
EPSILON = 1e-9


@dataclass(frozen=True)
class Threshold:
    """Where the next reading is expected, and the interval an ordinary one stays in."""

    expected: float
    low: float
    high: float
    # Past one-step-ahead errors the width stands on.
    scores: int

    def outside(self, value: float) -> bool:
        return value < self.low or value > self.high


def scores_needed(rate: float) -> int:
    """Past errors needed before an interval at `rate` exists: with fewer, the conformal
    quantile is the largest error or beyond, and nothing could be called unusual."""
    if not 0 < rate < 1:
        raise ValueError(f"rate must be between 0 and 1, got {rate}")
    return math.ceil(1 / rate) - 1


def first_forecast(period: int | None = None) -> int:
    """The index of the first reading that is forecast: after the warm-up, or, with a cycle,
    after `CYCLES_BEFORE` full cycles, so that no error is measured before the cycle is known."""
    return max(WARM_UP, CYCLES_BEFORE * period) if period and period >= 2 else WARM_UP


def readings_needed(rate: float, period: int | None = None) -> int:
    """Readings needed before the next one can be judged at `rate`."""
    return first_forecast(period) + scores_needed(rate)


def forecast(history: Sequence[float], period: int | None = None) -> float:
    """The expected next reading. Without a cycle: the median of the last `WINDOW` readings.
    With a cycle of `period` readings and at least `CYCLES_BEFORE` of them in the history: the
    median of the readings at the next reading's position in the last `CYCLES` cycles."""
    if not history:
        raise ValueError("a forecast needs at least one reading")
    n = len(history)
    if period is None or period < 2 or n < CYCLES_BEFORE * period:
        return median(history[-WINDOW:])
    return median(history[i] for i in range(n - period, max(-1, n - CYCLES * period - 1), -period))


def errors(values: Sequence[float], period: int | None = None) -> list[float]:
    """The absolute one-step-ahead error of each reading from `first_forecast` on, each
    forecast from the readings before it only."""
    return [abs(values[t] - forecast(values[:t], period)) for t in range(first_forecast(period), len(values))]


def conformal_width(scores: Sequence[float], rate: float) -> float | None:
    """The conformal width for `rate`: the ceil((m + 1)(1 - rate))-th smallest of the `m` past
    errors. For errors that are exchangeable, an ordinary one exceeds it with probability at
    most `rate`; rolling forecast errors are only roughly so, and the rate is checked by
    simulation (`tests/test_anomaly.py`). None while there are too few errors."""
    m = len(scores)
    if m < scores_needed(rate):
        return None
    rank = math.ceil((m + 1) * (1 - rate))
    return sorted(scores)[min(rank, m) - 1]


def threshold(
    history: Sequence[float], rate: float = DEFAULT_RATE, period: int | None = None
) -> Threshold | None:
    """The interval for the reading that follows `history`, or None while the history is too
    short for `rate` (`readings_needed`) or the interval cannot be written as finite numbers."""
    if len(history) < readings_needed(rate, period):
        return None
    scores = errors(history, period)
    width = conformal_width(scores, rate)
    if width is None:
        return None
    expected = forecast(history, period)
    width = max(width, EPSILON * max(1.0, abs(expected)))
    found = Threshold(expected=expected, low=expected - width, high=expected + width, scores=len(scores))
    # Readings near the largest float overflow in a median or a sum: no interval then, rather
    # than one with infinity or NaN in it.
    if not all(math.isfinite(x) for x in (found.expected, found.low, found.high)):
        return None
    return found


@dataclass(frozen=True)
class Judgement:
    """The newest reading against the interval built from the readings before it."""

    value: float
    threshold: Threshold | None

    @property
    def unusual(self) -> bool:
        return self.threshold is not None and self.threshold.outside(self.value)


def judge(values: Sequence[float], rate: float = DEFAULT_RATE, period: int | None = None) -> Judgement:
    """Judge the last of `values` by the ones before it."""
    if not values:
        raise ValueError("nothing to judge")
    return Judgement(value=values[-1], threshold=threshold(values[:-1], rate, period))
