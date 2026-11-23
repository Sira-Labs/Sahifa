"""Distances between a column's distribution at its baseline and now (spec 026).

Everything here works on what a profile already holds: seven points of the distribution
function for a numeric column (minimum, five quantiles, maximum) and the counts per value for
a column with few values. No query, no dependency.

A shift is reported on an effect size, never on significance alone: with a million rows every
difference is significant. Significance is the second condition, so that a small sample's
noise is not taken for a shift.

- Numeric: the Kolmogorov–Smirnov distance D (the largest difference in the share of values
  below any point) decides; the Wasserstein distance in interquartile ranges says how far the
  values moved.
- Few values: the Jensen–Shannon distance decides, and the population stability index (PSI)
  must exceed its critical value, a chi-square quantile scaled by the two sample sizes
  (Yurdakul and Naranjo, 2020) instead of the 0.1/0.25 rule of thumb.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

# The smallest effect reported: D for numbers, the Jensen–Shannon distance for few values.
MIN_EFFECT = 0.1
# Noise is ruled out at one in a thousand.
ALPHA = 0.001
KS_COEFFICIENT = math.sqrt(-math.log(ALPHA / 2) / 2)  # 1.95 at one in a thousand
Z_ALPHA = 3.0902  # the standard normal quantile at 1 - ALPHA
LEVELS = (0.01, 0.25, 0.5, 0.75, 0.99)
OTHER = "(other values)"

Points = Sequence[tuple[float, float]]


def points_of(minimum: float, quantiles: Mapping[str, float], maximum: float) -> list[tuple[float, float]]:
    """(value, share of values at or below it) from a profile: `p25` is the level 0.25."""
    points = [(float(minimum), 0.0)]
    points += sorted((float(v), int(k[1:]) / 100) for k, v in quantiles.items())
    points.append((float(maximum), 1.0))
    return points


def cdf_bounds(points: Points, x: float) -> tuple[float, float]:
    """The lowest and the highest share of values at or below `x` the points allow.

    Between two points the function is taken as linear, and both bounds are that value. Not so
    after a value that several points share: so many rows hold exactly that value that it
    spans more than one level, and its true share is only known to lie between the highest of
    those levels and the next point's. Reading it as the highest level would move a column
    with 26 % zeros and one with 24 % a quarter apart."""
    if x < points[0][0]:
        return 0.0, 0.0
    last = max(i for i, (v, _u) in enumerate(points) if v <= x)
    v0, u0 = points[last]
    if last == len(points) - 1:
        return 1.0, 1.0
    v1, u1 = points[last + 1]
    low = u0 + (u1 - u0) * (x - v0) / (v1 - v0)
    shared = last > 0 and points[last - 1][0] == v0
    return low, u1 if shared else low


def cdf(points: Points, x: float) -> float:
    """The share of values at or below `x`, linear between the known points (the lower bound
    where a shared value leaves it open)."""
    return cdf_bounds(points, x)[0]


def cdf_inverse(points: Points, level: float) -> float:
    """The value at a level the points carry (the median at 0.5)."""
    return next(v for v, u in points if abs(u - level) < 1e-9)


def ks_distance(reference: Points, current: Points) -> float:
    """The largest difference between the two distribution functions at any known point that
    the points prove: where a share is only known within bounds, the bounds' gap counts."""
    distance = 0.0
    for x in {v for v, _u in reference} | {v for v, _u in current}:
        (ref_low, ref_high), (cur_low, cur_high) = cdf_bounds(reference, x), cdf_bounds(current, x)
        distance = max(distance, ref_low - cur_high, cur_low - ref_high)
    return distance


def ks_critical(n: int, m: int) -> float:
    """The distance two samples of the same distribution exceed once in a thousand times."""
    return KS_COEFFICIENT * math.sqrt((n + m) / (n * m))


def _at_levels(points: Points) -> list[float] | None:
    by_level = {round(u, 2): v for v, u in points}
    return [by_level[u] for u in LEVELS] if all(u in by_level for u in LEVELS) else None


def wasserstein_in_iqr(reference: Points, current: Points) -> float | None:
    """The mean distance between equal quantiles, from the 1st to the 99th percentile, in
    interquartile ranges of the reference (in its 1 % to 99 % span when that range is zero).
    None when the reference has no spread to measure in."""
    ref, cur = _at_levels(reference), _at_levels(current)
    if ref is None or cur is None:
        return None
    scale = ref[3] - ref[1] or ref[4] - ref[0]
    if scale <= 0:
        return None
    gaps = [abs(a - b) for a, b in zip(ref, cur, strict=True)]
    area = sum((gaps[i] + gaps[i + 1]) / 2 * (LEVELS[i + 1] - LEVELS[i]) for i in range(len(LEVELS) - 1))
    return area / (LEVELS[-1] - LEVELS[0]) / scale


def bins_of(
    reference: Mapping[str, int], current: Mapping[str, int], current_rows: int
) -> list[tuple[str, int, int]]:
    """(value, count at the baseline, count now) per baseline value, and one more bin for
    every value the baseline did not have."""
    bins = [(value, count, current.get(value, 0)) for value, count in sorted(reference.items())]
    other = current_rows - sum(now for _v, _c, now in bins)
    if other > 0:
        bins.append((OTHER, 0, other))
    return bins


def total_variation(bins: Sequence[tuple[str, int, int]]) -> float:
    """The share of rows that would have to change their value to undo the difference."""
    m, n = sum(b[1] for b in bins), sum(b[2] for b in bins)
    return sum(abs(ref / m - cur / n) for _v, ref, cur in bins) / 2


def js_distance(bins: Sequence[tuple[str, int, int]]) -> float:
    """Jensen–Shannon distance (base 2): 0 for equal shares, 1 for no value in common."""
    m, n = sum(b[1] for b in bins), sum(b[2] for b in bins)
    divergence = 0.0
    for _v, ref, cur in bins:
        p, q = ref / m, cur / n
        mid = (p + q) / 2
        if p:
            divergence += p * math.log2(p / mid) / 2
        if q:
            divergence += q * math.log2(q / mid) / 2
    return math.sqrt(max(divergence, 0.0))


def psi(bins: Sequence[tuple[str, int, int]]) -> float:
    """Population stability index; half a row is added to every bin, so an empty one counts."""
    m = sum(b[1] for b in bins) + len(bins) / 2
    n = sum(b[2] for b in bins) + len(bins) / 2
    total = 0.0
    for _v, ref, cur in bins:
        p, q = (ref + 0.5) / m, (cur + 0.5) / n
        total += (q - p) * math.log(q / p)
    return total


def chi_square_quantile(df: int) -> float:
    """The chi-square quantile at 1 - ALPHA (Wilson–Hilferty, within 3 % from one degree on)."""
    spread = 2 / (9 * df)
    return float(df * (1 - spread + Z_ALPHA * math.sqrt(spread)) ** 3)


def psi_critical(bins: int, n: int, m: int) -> float:
    """The PSI two samples of the same distribution exceed once in a thousand times: under no
    change PSI is about a chi-square variable with `bins - 1` degrees times (1/n + 1/m)."""
    return chi_square_quantile(max(bins - 1, 1)) * (1 / n + 1 / m)
