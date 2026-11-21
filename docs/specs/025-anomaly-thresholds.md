# Spec 025 — Anomaly thresholds on measure history

Sprint 5, story S5-2 (check 17, `sah.metric_anomaly`: the thresholds). Depends on: spec 024
(measure history per column), spec 017 (role matrix), ADR-0004 (scores with intervals; it
announces conformal thresholds for history-based checks), ADR-0017 (medians instead of STL,
written with this spec), ADR-0016. Packages: `core/`, `api/`, `docs/`.

Status: written and implemented by the nightly run of 22 November 2026 (ADR-0016).

## Goal

For every measure Sahifa keeps per column, say whether the newest scan's value is unusual
given the scans before it, and where the next scan's value is expected, at a false-alarm
rate a person chooses. "Unusual" has to mean something: at a rate of 5 %, about one ordinary
reading in twenty is reported, not more. Gate G2 asks for exactly that on synthetic history.

## User story

As a data engineer, I ask for a column's thresholds and see that its null share, usually 0 to
1 %, was 40 % in last night's scan, so that I look at the load before a rule exists for it.

## Interface

### Core: `sahifa_core.anomaly`

| Function | Meaning |
|---|---|
| `forecast(history, period=None)` | the expected next reading (the baseline) |
| `errors(values, period=None)` | the absolute one-step-ahead errors of the baseline over a history |
| `threshold(history, rate=0.05, period=None)` | `Threshold(expected, low, high, scores)` for the next reading, or `None` while the history is too short |
| `judge(values, rate=0.05, period=None)` | the last value against the threshold from the ones before it: `.unusual` |
| `readings_needed(rate, period=None)` | how many readings a threshold at `rate` needs |

### API: `GET /api/assets/{asset_id}/measures/thresholds`

| | |
|---|---|
| Query | `column` (required), `rate` (0.01 to 0.5, default 0.05) |
| Role | viewer of the table's workspace |
| Success | `200` `{"asset_id", "column", "rate", "period", "measures": {name: {...}}}` |
| Per measure | `value` (the newest scan's, or null), `newest` and `next` (each `{expected, low, high, scores}` or null; `newest` also has `unusual`), `scans`, `scans_needed` |
| Errors | `404` for a table the caller does not see; `404 column_not_found` as in spec 024; `422` for a rate outside the range |

## Behaviour

1. **Baseline.** Without a cycle, the expected next reading is the median of the last 10
   readings. With a cycle of `period` readings and at least 2 full cycles of history, it is the
   median of the readings at the same position in the last 4 cycles (ADR-0017).
2. **Errors.** For each reading after a warm-up (3 readings, or 2 cycles), the absolute
   difference to the baseline computed from the readings before it only.
3. **Interval.** With `m` past errors, the width is the `ceil((m + 1)(1 - rate))`-th smallest:
   an ordinary error exceeds it with probability at most `rate`. The interval is the baseline
   plus and minus the width.
4. **Enough history.** A threshold needs `ceil(1 / rate) - 1` errors: 19 at 5 %, 9 at 10 %, 99
   at 1 %. With the warm-up that is 22 scans at 5 % (33 with a weekly cycle). Until then the
   answer says how many scans there are and how many are needed, and nothing is called
   unusual.
5. **A constant series** has a width of zero; the width is then a billionth of the level, so
   floating-point noise is not a change and any real change is.
6. **The API** reads the column's last 120 scans. For each measure it returns the newest
   reading judged by the scans before it, and the interval for the next scan.
   - A scan without the measure (an empty table) is left out of that measure's history; when
     the newest scan lacks it, `value` and `newest` are null.
   - Shares stay in 0 to 1: their intervals are cut there.
   - **Cycle.** When the scans come once a day (the median gap between them is a day, give or
     take three hours, over at least 15 scans), the history is read with a weekly cycle and
     `period` is 7. A measure that some scans lack is read without it.
7. **What the rate promises** (gate G2, `core/tests/test_anomaly.py`, 4,000 simulated
   histories of 60 readings per case):

   | History | Read | Measured false-alarm rate at a chosen 5 %, 10 %, 20 % |
   |---|---|---|
   | level with normal noise | no cycle | within the rate (plus three standard errors) |
   | skewed (a share near zero) | no cycle | within the rate |
   | weekly dip | weekly cycle | within the rate |
   | no cycle at all | weekly cycle | within the rate |
   | steady trend | no cycle | at most 10 % at a chosen 5 % |
   | weekly dip | no cycle | at most 10 % at a chosen 5 % |

   A shift of eight standard deviations in the last reading is found in at least 95 % of the
   modelled cases; for the trend and the unmodelled dip the shift has to be larger than what
   the baseline misses.

## Acceptance criteria

- [x] `threshold` and `judge` follow behaviours 1 to 5; too little history gives no threshold.
- [x] Gate G2: the false-alarm rates of the table above hold in the test, and injected shifts
      are found.
- [x] `GET /api/assets/{id}/measures/thresholds?column=` returns per measure the judged newest
      reading and the next interval; a jump in a measure is `unusual`; a stricter rate reports
      how many scans it needs.
- [x] A daily history is read with a weekly cycle; an irregular one without.
- [x] A viewer reads it; another workspace's table is 404 (role matrix,
      `test_every_route_is_classified` green).
- [x] No new runtime dependency.
- [x] `make lint` and `make test` clean.

## Test cases

Unit (`core/tests/test_anomaly.py`): needed scores and readings; forecast with and without a
cycle; one-step-ahead errors; the ranked width; thresholds and too little history; a constant
series; `judge`; the gate cases above.

Unit (`api/tests/test_measures.py`): `period_of`; thresholds for a mean and a jumping null
share; shares cut at 0 and 1; too little history; a newest scan without the measure; a daily
history with a weekend dip.

Integration (`api/tests/test_measures.py`): `test_thresholds_through_the_api`.
Role matrix (`api/tests/test_matrix.py`): the route, viewer, read.

## Decisions

- **Medians instead of STL, and no statsmodels:** ADR-0017.
- **The thresholds are computed when asked, not stored.** They are cheap (120 readings), and
  a stored threshold would have to be recomputed after every scan anyway. S5-4 stores what
  becomes a finding.
- **The rate is a query parameter with a default of 5 %,** not yet a setting per check: the
  check that carries it arrives with S5-4.
- **120 scans** are read: enough for a rate of 1 % (102 scans), and bounded.
- **Only the weekly cycle of daily scans is recognised.** Other cycles are read without one,
  which widens the interval (behaviour 7) instead of raising alarms.
- The role matrix has 35 workspace operations now (spec 024 counted 34).

## Out of scope

- Anomalies as findings, thresholds on the column page's charts, a rate per check: S5-4.
- Check 16 (`sah.distribution_shift`) and drift between scans: S5-3.
- Minimum and maximum of dates; a row-count series per table; trend-aware baselines for
  tables that grow (ADR-0017, alternatives).
- Trimming `column_measures`: the backlog entry of spec 024 now has its number, 120 scans.
