# ADR-0017: Anomaly baselines from medians, not STL; conformal intervals as planned

- **Status:** Accepted
- **Date:** 2026-11-22
- **Deciders:** nightly run (ADR-0016)
- **Amends:** the method named for check 17 in `docs/checks/catalogue.md`, sprint story S5-2 and
  `docs/research/03-research-methods.md` ("STL plus seasonal baselines (statsmodels)")

## Context

Check 17 (`sah.metric_anomaly`) reads the history of a measure and says whether the newest
reading is unusual, at a false-alarm rate a person chooses. The plan named an STL baseline
(seasonal-trend decomposition by LOESS, from statsmodels) with conformal thresholds.

What a Sahifa history looks like, since spec 024:

- **Short.** A threshold at a rate of 5 % can start after about 22 scans, and the page shows
  30. STL needs at least two full cycles and behaves well with many more.
- **Irregular.** Most scans are started by hand or on mixed schedules. STL assumes evenly
  spaced readings with a known period.
- **Read by people.** A finding has to say why: "the mean is usually 40 to 44, now 61".

And what the dependency would cost: statsmodels brings NumPy, SciPy, pandas and patsy into the
core library and the API image, which so far have four runtime dependencies and need no
compiler.

## Decision

1. **The baseline is a median, not STL.**
   - Without a cycle: the median of the last 10 readings.
   - With a cycle (an unbroken series of daily scans is read with a weekly cycle): the median of
     the readings at the same position in the last 4 cycles, once 2 cycles are complete.
2. **The interval is conformal, as planned:** the baseline's own absolute one-step-ahead errors
   over the history give the width that an ordinary reading exceeds with probability at most
   the chosen rate (split conformal on rolling forecasts). No distribution is assumed.
3. **No new runtime dependency.** `sahifa_core.anomaly` is arithmetic on a list of numbers.
4. **Gate G2 is a test:** `core/tests/test_anomaly.py` simulates 4,000 histories per case and
   checks the false-alarm rate against the chosen rate, and that injected shifts are found.

## Consequences

- The false-alarm rate holds where the baseline models the series: level noise of any shape
  (normal or skewed) and a weekly cycle read with its period. The test allows three standard
  errors above the chosen rate.
- What the baseline does not model goes into the errors and widens the interval: a steady
  trend (the median lags it) and a cycle read without its period. There the measured
  false-alarm rate at a chosen 5 % stays below 10 % in the test, and shifts must be larger to be
  found. The spec states this bound instead of promising the rate everywhere.
- Rolling one-step-ahead errors are not exactly exchangeable, so the guarantee is empirical
  (the gate test), not the textbook one.
- A history with a cycle other than weekly (hourly loads, month ends) is read without it.
- If histories become long and regular (scheduled scans as the norm), STL or a weighted
  conformal variant can replace `forecast` without changing the interface: `threshold` takes a
  history and returns an expected value and an interval.

## Alternatives considered

| Alternative | Why not |
|---|---|
| STL from statsmodels | Four heavy dependencies for a method that needs regular, long histories Sahifa does not have yet |
| Mean and three standard deviations | Assumes a normal curve; a null share near zero is nothing like one, and one outlier inflates the width |
| Median and MAD with a fixed factor | Robust, but the false-alarm rate is whatever the data makes it, not a chosen one |
| A fitted trend line plus conformal errors | Removes the lag on steady trends; adds a fit that short, noisy histories make unstable. Left for when a table's growth produces alarms in practice |
