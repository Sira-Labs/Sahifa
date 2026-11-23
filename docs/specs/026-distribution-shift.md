# Spec 026 — Distribution shift against the locked baseline

Sprint 5, story S5-3 (check 16, `sah.distribution_shift`). Depends on: spec 003 (check
contract), spec 007 and ADR-0005 (baselines are proposed, then locked), spec 014 (accuracy
benchmark, drift twin), ADR-0004 (scores with intervals), ADR-0016. Packages: `core/`, `docs/`.

Status: written and implemented by the nightly run of 23 November 2026 (ADR-0016).

## Goal

A column whose values are all still allowed can change all the same: half of the orders are
suddenly cancelled, or the amounts are twice what they were. Once the owner has locked a
column's distribution baseline, every later scan says whether the distribution moved, by how
much, and how that number is to be read. A report means a change somebody would call a change:
it rests on an effect size, and on significance only so that the noise of a small sample is
not taken for one.

## User story

As a data owner, I approve the distribution of `events.kind` as it is today and learn from a
later scan that the share of checkouts went from 33 % to 50 %, so that I ask the shop team
before the conversion report goes out.

## Interface

### Core: `sahifa_core.drift`

| Function | Meaning |
|---|---|
| `points_of(min, quantiles, max)` | the distribution function at seven points, from a profile |
| `cdf(points, x)` | the share of values at or below `x`, linear between the points |
| `ks_distance(reference, current)` | the largest difference of the two functions at any known point |
| `ks_critical(n, m)` | the distance two samples of one distribution exceed once in a thousand times |
| `wasserstein_in_iqr(reference, current)` | the mean distance between equal quantiles (1st to 99th percentile), in interquartile ranges of the reference |
| `bins_of(reference, current, rows)` | counts per baseline value, plus one bin for values the baseline did not have |
| `js_distance(bins)`, `total_variation(bins)`, `psi(bins)` | distances between two mixes of values |
| `psi_critical(bins, n, m)` | the PSI two samples of one distribution exceed once in a thousand times |

Constants: `MIN_EFFECT = 0.1`, `ALPHA = 0.001`.

### Check `sah.distribution_shift`

| | |
|---|---|
| Dimension, level, kind | accuracy, column, baseline (proposed until locked) |
| Severity | medium |
| Evaluation | profile (no query of its own) |
| Applies to | a column with at least 100 values that is not a key, a foreign key, a timestamp or personal data, and is either a number column with more than one value, or a text or integer column with 2 to 20 distinct values (at most 20 % of its rows) |
| Parameters, numbers | `{"form": "numeric", "rows", "quantiles": {"min", "p01", "p25", "p50", "p75", "p99", "max"}}` |
| Parameters, few values | `{"form": "values", "rows", "counts": {value: count}}` |
| Measured (in the result's parameters) | numbers: `distance`, `threshold`, `moved_iqr`, `median` (before, now); few values: `distance`, `threshold`, `psi`, `psi_critical`, `changed` |

No new route, table or setting: the check travels through the scan, the checks page and the
findings like every baseline check.

## Behaviour

1. **Baseline.** A scan proposes the check with the column's distribution as the profile has
   it: for numbers the minimum, the 1 %, 25 %, 50 %, 75 % and 99 % quantiles and the maximum;
   for a column with few values the count of each value. While the check is proposed, each scan
   replaces these parameters (spec 007), so it compares the column with itself and passes.
   Locked, the parameters stay and later scans are measured against them. "Approve the new
   baseline" works as for every baseline check.
2. **Numbers.** The distance is Kolmogorov–Smirnov's D: the largest difference between the
   share of values at or below a point at the baseline and now, taken at every point either
   profile holds, with the distribution function linear between the points. The check fails
   when D is at least 0.1 **and** at least the critical value `1.95 · sqrt((n + m) / (n · m))`
   for the two numbers of rows (one in a thousand for samples of one distribution). The larger
   of the two is the `threshold` shown. The Wasserstein distance, the mean distance between
   equal quantiles, is reported in interquartile ranges of the baseline as the size of the
   move; it does not decide, and is left out when the baseline has no spread between its 1 %
   and 99 % quantiles.
3. **Few values.** The bins are the baseline's values, and one more for every value that is
   new. The check fails when the Jensen–Shannon distance (base 2, between 0 and 1) is at least
   0.1 **and** the population stability index is at least its critical value: the 99.9 %
   quantile of the chi-square distribution with (bins − 1) degrees of freedom, times
   `1/n + 1/m`. PSI is computed with half a row added to every bin, so an empty bin counts
   without making it infinite. The fixed marks 0.1 and 0.25 for PSI are not used: with ten
   values and 200 rows ordinary samples exceed 0.1, and with a million rows a PSI of 0.01 is
   far beyond chance.
4. **Counts.** `evaluated` is the number of values now. `failed` is 0 when the check passes.
   When it fails, it is the smallest number of rows that must have changed: `ceil(D · n)` for
   numbers, the total variation distance times `n` for few values (exact when rows moved from
   one value to another). So the finding weighs in the score like that share of failing rows.
5. **Explanation.** The summary names both numbers and the mark they are read against, for
   example "Jensen–Shannon distance 0.18 (reported from 0.10), PSI 0.190 (critical value
   0.011); at least 17.1 % of the rows have another value than before", or "Kolmogorov–Smirnov
   distance 0.24 (reported from 0.10), on average by 0.25 interquartile ranges (Wasserstein);
   the median went from 2,581 to 3,393.5". A finding on few values lists the values whose
   share moved most as examples ("checkout: 32.7 % → 49.8 %", with the rows now). A passing
   check says the distance it measured.
6. **Not comparable.** A locked numeric baseline on a column that holds no numbers any more is
   evaluated on 0 rows and passes with "could not be compared"; type conformance reports the
   cause. A column that is gone is listed as unevaluated, as for every saved check.
7. **Other baselines keep their findings.** A handful of rows with a value never seen
   (`sah.accepted_values`) or below the smallest value seen (`sah.range`) do not move the
   distribution by a tenth and are not reported here.

### Decisions

- **Against the locked baseline, not the previous scan** (the catalogue said "previous scan").
  A comparison scan by scan never sees a slow drift, and it reports a change once and then
  accepts it without anyone having decided. The baseline lifecycle (ADR-0005) already gives
  the reference a person approved; the measures over time (spec 024) and their thresholds
  (spec 025) are what watches scan-to-scan movement.
- **On the profile, without a query.** Seven points of the distribution function and the
  counts of the top values are in every profile. KS on seven points is a lower bound of the
  true distance: a change inside one quarter that leaves all five quantiles in place is not
  seen. A finer grid would need more quantiles in the profile and in the stored measures
  (spec 024); left for the day a missed shift shows the need.
- **Effect size 0.1 for both forms.** D = 0.1: a tenth of the rows lie on the other side of
  some point. A Jensen–Shannon distance of 0.1 is about a tenth of the rows changing between
  two values of similar size. Both are fixed for now; a per-check setting can come with the
  check editor.
- **One in a thousand for the noise condition**, not 5 %: a store has hundreds of columns, and
  a locked baseline is evaluated on every scan.
- **No timestamps.** A timestamp column moves forward with every load; freshness and the range
  baseline cover it.
- **The benchmark covers every check of the catalogue** (`accuracy.CHECKS`), not only R1; the
  drift twin gains two shifted columns in `events` (`kind`: half of the views become
  checkouts; `payload_size`: half of the values below 2,500 take a value from above).

## Acceptance criteria

- [x] On the drift twin, scanned against the clean twin's locked baselines, `events.kind` and
      `events.payload_size` are findings of `sah.distribution_shift`, each with its effect size
      in the summary and in `measured`; no other column is.
- [x] The clean twin against its own locked baselines has no finding and a distance of 0 for
      every distribution check; a clean shop of another seed, read in full and through a
      sample of 1,000 rows, has no distribution finding.
- [x] `sahifa bench-accuracy --seeds 20 --rows 5000 --sample-rows 500`: 40 of 40 shifts
      detected, 0 unexpected results, 0 findings of 200 locked baselines on new data.
- [x] Two samples of one distribution (100 to 5,000 rows, numbers and ten values) are called
      shifted in at most 3 of 600 comparisons.
- [x] The check is proposed, never scored, until locked; `make lint` and `make test` pass.

## Test cases

Unit (`core/tests/test_drift.py`): `test_points_and_distribution_function`,
`test_ks_distance_of_a_location_shift`, `test_ks_distance_sees_a_change_of_spread`,
`test_ks_critical_value_shrinks_with_the_samples`, `test_wasserstein_in_interquartile_ranges`,
`test_bins_keep_the_baseline_values_and_collect_new_ones`, `test_distances_between_value_mixes`,
`test_chi_square_quantile_and_psi_critical_value`,
`test_same_distribution_stays_below_the_thresholds`.

On the shop (same file): `test_baselines_are_proposed_for_numbers_and_few_values`,
`test_shifted_mix_is_reported_with_its_effect_size`,
`test_shifted_numbers_are_reported_with_their_effect_size`,
`test_only_the_shifted_columns_are_reported`, `test_clean_twin_stays_silent`,
`test_new_clean_data_stays_silent`, `test_column_that_lost_its_numbers_is_not_compared`.

Benchmark (`core/tests/test_accuracy.py`): `test_fault_list_counts_match_the_files` (the two
shift faults are recounted from the files), `test_every_check_has_a_fault`,
`test_benchmark_small_run`.

## Out of scope

- Checks 24 (`sah.schema_drift`) and 29 (`sah.volume_trend`), which the sprint plan lists
  with this story: each needs history the scan does not hand to the core yet; they stay in
  the backlog under sprint 5.
- The chart of a shifted distribution and anomalies as findings: S5-4.
- More quantiles in the profile, and thresholds per check: see Decisions.
