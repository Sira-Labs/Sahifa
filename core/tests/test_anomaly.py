"""Anomaly thresholds (spec 025): the arithmetic, and gate G2: on synthetic history the
false-alarm rate stays within the chosen rate, and injected shifts are found."""

from __future__ import annotations

import math
import random

import pytest

from sahifa_core.anomaly import (
    DEFAULT_RATE,
    WARM_UP,
    Threshold,
    conformal_width,
    errors,
    first_forecast,
    forecast,
    judge,
    readings_needed,
    scores_needed,
    threshold,
)

# --- The arithmetic --------------------------------------------------------------------------


def test_scores_and_readings_needed() -> None:
    assert scores_needed(0.05) == 19
    assert scores_needed(0.1) == 9
    assert scores_needed(0.01) == 99
    assert readings_needed(0.05) == WARM_UP + 19
    # With a cycle, nothing is forecast before two full cycles.
    assert first_forecast() == WARM_UP and first_forecast(1) == WARM_UP and first_forecast(7) == 14
    assert readings_needed(0.05, period=7) == 14 + 19
    for bad in (0, 1, -0.1, 1.5):
        with pytest.raises(ValueError, match="rate must be between 0 and 1"):
            scores_needed(bad)


def test_forecast_is_the_median_of_the_last_readings() -> None:
    assert forecast([5.0]) == 5.0
    assert forecast([1, 2, 100]) == 2
    # Only the last ten count: the level follows a series that moved.
    assert forecast([0] * 50 + [10] * 10) == 10
    with pytest.raises(ValueError, match="at least one reading"):
        forecast([])


def test_forecast_reads_the_same_position_of_the_last_cycles() -> None:
    # A week of 100 on six days and 160 on the seventh, three weeks: the next is a seventh day.
    weeks = ([100.0] * 6 + [160.0]) * 3
    assert forecast(weeks[:-1]) == 100
    assert forecast(weeks[:-1], period=7) == 160
    # The day after is an ordinary one again.
    assert forecast(weeks, period=7) == 100
    # Fewer than two full cycles: the level alone.
    assert forecast(weeks[:13], period=7) == 100
    assert forecast([1, 2, 3], period=1) == 2
    # Only the last four cycles count: the seventh day moved from 160 to 300.
    moved = ([100.0] * 6 + [160.0]) * 3 + ([100.0] * 6 + [300.0]) * 4
    assert forecast([*moved, *[100.0] * 6], period=7) == 300


def test_errors_are_one_step_ahead() -> None:
    values = [10.0, 10, 10, 13, 10, 10]
    # Readings 3, 4 and 5 against the median of what came before each.
    assert errors(values) == [3, 0, 0]
    assert errors([1.0, 2, 3]) == []
    # With a cycle, the first error is measured after two full cycles.
    weeks = ([100.0] * 6 + [160.0]) * 3
    assert errors(weeks, period=7) == [0.0] * 7


def test_conformal_width_is_the_ranked_past_error() -> None:
    scores = [float(i) for i in range(1, 20)]  # 19 errors: 1..19
    assert conformal_width(scores, 0.05) == 19  # ceil(20 * 0.95) = 19th smallest
    assert conformal_width(scores, 0.1) == 18  # ceil(20 * 0.9) = 18th
    assert conformal_width(scores[:18], 0.05) is None
    assert conformal_width([float(i) for i in range(1, 100)], 0.5) == 50


def test_threshold_needs_enough_history_and_brackets_the_forecast() -> None:
    rng = random.Random(1)
    values = [50 + rng.gauss(0, 2) for _ in range(40)]
    assert threshold(values[: readings_needed(DEFAULT_RATE) - 1]) is None
    found = threshold(values)
    assert isinstance(found, Threshold)
    assert found.low < found.expected < found.high
    assert found.scores == len(values) - WARM_UP
    assert found.expected == forecast(values)
    assert (
        not found.outside(found.expected) and found.outside(found.high + 1) and found.outside(found.low - 1)
    )
    # A wider interval for a lower false-alarm rate needs more history.
    assert threshold(values, rate=0.01) is None
    wide, narrow = threshold(values, rate=0.05), threshold(values, rate=0.2)
    assert wide is not None and narrow is not None
    assert wide.high - wide.low >= narrow.high - narrow.low


def test_a_constant_series_tolerates_noise_but_not_a_change() -> None:
    constant = [0.25] * 30
    assert not judge([*constant, 0.25 + 1e-15]).unusual
    assert judge([*constant, 0.26]).unusual


def test_judge_reads_the_last_value_against_the_ones_before() -> None:
    rng = random.Random(2)
    values = [1000 + rng.gauss(0, 10) for _ in range(40)]
    ordinary = judge(values)
    assert ordinary.value == values[-1] and ordinary.threshold == threshold(values[:-1])
    assert judge([*values, 2000.0]).unusual
    # Too little history: nothing is called unusual.
    short = judge([1.0, 2.0, 500.0])
    assert short.threshold is None and not short.unusual
    with pytest.raises(ValueError, match="nothing to judge"):
        judge([])


# --- Gate G2: the false-alarm rate on synthetic history ---------------------------------------

TRIALS = 4000
LENGTH = 60
SIGMA = 5.0


def stationary(rng: random.Random, n: int) -> list[float]:
    return [200 + rng.gauss(0, SIGMA) for _ in range(n)]


def trending(rng: random.Random, n: int) -> list[float]:
    """A table that grows by a steady amount per scan."""
    return [1000 + 4 * i + rng.gauss(0, SIGMA) for i in range(n)]


def weekly(rng: random.Random, n: int) -> list[float]:
    """A daily load with a weekend dip."""
    return [500 - (120 if i % 7 in (5, 6) else 0) + rng.gauss(0, SIGMA) for i in range(n)]


def skewed(rng: random.Random, n: int) -> list[float]:
    """A share near zero with occasional larger values: nothing like a normal curve."""
    return [rng.expovariate(1 / 0.01) for _ in range(n)]


def alarm_share(make, *, rate: float, period: int | None, shift: float = 0.0, seed: int = 7) -> float:
    """The share of `TRIALS` synthetic histories whose last reading, moved by `shift`, is
    called unusual."""
    rng = random.Random(seed)
    alarms = 0
    for _ in range(TRIALS):
        values = make(rng, LENGTH)
        values[-1] += shift
        alarms += judge(values, rate, period).unusual
    return alarms / TRIALS


def allowed(rate: float) -> float:
    """`rate` plus three standard errors of a share measured on `TRIALS` trials."""
    return rate + 3 * math.sqrt(rate * (1 - rate) / TRIALS)


@pytest.mark.parametrize("rate", [0.05, 0.1, 0.2])
@pytest.mark.parametrize(
    ("make", "period"),
    [(stationary, None), (skewed, None), (weekly, 7), (stationary, 7)],
    ids=["stationary", "skewed", "weekly with its period", "stationary read as weekly"],
)
def test_false_alarm_rate_is_within_the_chosen_rate(make, period: int | None, rate: float) -> None:
    share = alarm_share(make, rate=rate, period=period)
    assert share <= allowed(rate), f"{share:.3f} > {allowed(rate):.3f}"
    # And the interval is not so wide that nothing is ever reported.
    assert share >= rate / 3, share


@pytest.mark.parametrize(
    ("make", "period", "shift"),
    [
        (stationary, None, 8 * SIGMA),
        (stationary, None, -8 * SIGMA),
        (weekly, 7, 8 * SIGMA),
        (skewed, None, 0.2),
    ],
    ids=["level up", "level down", "weekly, level up", "share jumps"],
)
def test_an_injected_shift_is_found(make, period: int | None, shift: float) -> None:
    assert alarm_share(make, rate=0.05, period=period, shift=shift) >= 0.95


def test_a_trend_and_an_unmodelled_season_widen_the_interval_but_stay_usable() -> None:
    """What the baseline does not model (a steady trend lags the median; a weekly dip read
    without its period) ends up in the errors, so the interval widens. The false-alarm rate may
    then be above the chosen one, by a bounded amount; the spec states the bound."""
    assert alarm_share(trending, rate=0.05, period=None) <= 0.10
    assert alarm_share(weekly, rate=0.05, period=None) <= 0.10
    # A shift well beyond the trend's lag and the dip is still found.
    assert alarm_share(trending, rate=0.05, period=None, shift=20 * SIGMA) >= 0.95
    assert alarm_share(weekly, rate=0.05, period=None, shift=60 * SIGMA) >= 0.95
