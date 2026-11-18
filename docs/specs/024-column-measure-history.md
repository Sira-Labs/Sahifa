# Spec 024 — Measure history per column

Sprint 5, story S5-1. Depends on: spec 007 (assets, columns and checks persisted), spec 011
(score history, whose shape this follows), spec 016 (workspaces, row-level security), spec 017
(role matrix), ADR-0016 (nightly runs: no approval step). Packages: `api/`, `web/`, `docs/`.

Status: written and implemented by the nightly run of 19 November 2026 (ADR-0016).

## Goal

Sahifa remembers what it measured. Each successful scan stores, for every column, the
measures of its profile: the shares of empty and distinct values, the mean, the spread, the
quantiles, and the row count of its table. A column's page shows them over the last scans, so
a person sees that a column changed before a rule breaks, and sprint 5's anomaly thresholds
(S5-2) and drift (S5-3) have a series to work on.

## User story

As a data engineer, I open a column and see its null share, distinct share, mean and
quantiles over the last 30 scans, so that I notice a change in the data that no check
reports yet.

## Interface

### Stored: `column_measures`

One row per scan, table and column.

| Column | Type | Meaning |
|---|---|---|
| `scan_id`, `connection_id`, `asset_id` | uuid | the scan, its store, the table (all cascade) |
| `column_name` | text | the column, by name: a scan replaces the `columns` rows |
| `measured_at` | timestamptz | the scan's `finished_at` |
| `rows` | bigint | rows the profile read |
| `population` | bigint, null | rows in the table, where the scan knows them |
| `sampled` | boolean | the profile read a sample, not every row |
| `measures` | jsonb | `{name: number}`, see below |
| `workspace_id` | uuid | from the table, filled by trigger; under row-level security |

Unique on (`scan_id`, `asset_id`, `column_name`); the history reads one index range on
(`asset_id`, `column_name`, `measured_at` descending).

### Measures

| Name | Meaning | Present for |
|---|---|---|
| `null_share` | nulls / rows read | every column with rows |
| `distinct_share` | distinct values / rows with a value | where the profile counted distinct values |
| `blank_share` | blank texts / rows read | text |
| `mean`, `stddev`, `min`, `max` | of the values | numbers |
| `p01`, `p25`, `p50`, `p75`, `p99` | quantiles | numbers |
| `mean_length` | mean length in characters | text |

Only finite numbers are stored; a measure the profile does not have is absent, not null.

### API: `GET /api/assets/{asset_id}/measures`

| | |
|---|---|
| Query | `column` (required, the column's name), `limit` (1 to 100, default 30) |
| Role | viewer of the table's workspace (as every read) |
| Success | `200` `{"asset_id", "column", "points": [...]}`, oldest first, the last `limit` scans |
| Point | `scan_id`, `finished_at`, `trigger`, `rows`, `population`, `sampled`, `measures` |
| Errors | `404` for a table the caller does not see; `404 column_not_found` for a name that is neither a column of the table now nor in its history |

### Web: `/assets/$assetId/columns/$column`

| Where | What |
|---|---|
| the page | the table and column, its type and role; per measure a small chart over the scans with the newest value and its range; below, a table with one row per scan |
| `/scans/$scanId/assets/$asset`, a column's expanded profile | a link *Measures over time* to the page |

## Behaviour

1. **Writing.** When a scan succeeds, the transaction that stores its report, checks, findings
   and scores also inserts one `column_measures` row per column of every table that has an
   asset row. A table the scan could not persist, or whose profile failed, writes none.
2. **What is measured** comes from the report's column profiles, with no further query against
   the source. Shares are computed from the profile's counts; a share whose denominator is
   zero is absent.
3. **Sampling.** `rows` and `sampled` say what the numbers stand on. A measure from a sample is
   an estimate; the page says so where a point was sampled.
4. **Reading** returns the last `limit` points of the table's column, oldest first, each with
   its scan's trigger. A column that exists but has no history yet answers 200 with no points.
5. **A column that disappeared** keeps its history: the page still opens from an old report.
6. **Deleting** a scan, a table, a connection or a workspace removes the measures with it
   (cascades; a workspace's connections are deleted, spec 020). **Moving** a connection to
   another workspace moves its measures with it (spec 016).
7. **The page** shows, in this order and only where at least one point has the measure: null
   share, distinct share, blank share, mean, standard deviation, minimum, maximum, the five
   quantiles, mean length. Each chart has a text alternative (first, newest, lowest, highest).
   Shares are shown as percentages. With one point, the chart is a single mark and the text
   says that a second scan makes a line. The table lists the scans newest first, each linking
   to its report, with rows read (marked when sampled), rows in the table and the measures.
8. **States.** Loading and failure as elsewhere (`ErrorPanel` with *Retry*); no history yet:
   a sentence that the next scan starts it.

## Acceptance criteria

- [x] A successful scan of the faulty shop writes one row per column, with `null_share` for
      every column the profile read rows of and mean and quantiles for numeric ones; a failed
      scan writes none.
- [x] `GET /api/assets/{id}/measures?column=amount` returns the points oldest first with the
      scans' triggers; `limit` cuts to the newest; an unknown column is 404 `column_not_found`.
- [x] A viewer reads it; another workspace's table is 404 (role matrix,
      `test_every_route_is_classified` green); `column_measures` is under forced row-level
      security.
- [x] Deleting a workspace with scanned data still works, and its measures are gone; moving
      a connection moves them.
- [x] Migration 0012 round-trips; `alembic check` is clean.
- [x] The column page shows a chart per measure with its text alternative, the table of scans,
      and the empty and failure states; the asset page links to it.
- [x] `make lint` and `make test` clean.

## Test cases

Unit (`api/tests/test_measures.py`): `measures_of` for a numeric, a text and an empty
profile; non-finite values and zero denominators are left out.

Integration (`api/tests/test_measures.py`, with a database):
- `test_scan_writes_measures`: three scans of the shop; rows per column; the API's points,
  order, `limit`, triggers; a text and a timestamp column.
- `test_unknown_columns_and_tables`: a column without history, one that never existed, one
  that is gone but has history; rows go with their scan.
- `test_failed_scan_writes_none`.
- `test_migration_0012_round_trips`, with forced row-level security.

Role matrix (`api/tests/test_matrix.py`): `GET /api/assets/{asset}/measures`, viewer, read.
Workspaces and tenancy (`api/tests/tenancy.py`, `test_workspaces.py`, `test_rls.py`):
`column_measures` is the twelfth workspace-owned table in every tree, so the delete, move,
trigger and visibility tests cover it.

Unit (`web/src/__tests__/ColumnMeasures.test.tsx`): series, formatting and chart positions;
charts and text alternatives for two measures; the table newest first with links; one point;
no points; a column that is gone; failure with retry. `Checks.test.tsx`: the link from a
column's profile.

## Decisions

- **One JSON object of measures per row,** not a column per measure and not a row per
  measure: a scan of 1,000 tables with 30 columns writes 30,000 rows, the set of measures can
  grow without a migration, and a history is one index range (as `scores.dimensions`).
- **By column name, not by a column id:** `columns` rows are replaced by every scan (spec 007),
  and a renamed column is a new series, which is what a reader expects.
- **Minimum and maximum of dates and timestamps are not stored yet.** They are text in the
  profile; S5-2 decides how growing timestamps are baselined (the follow-up of spec 014).
- **No pass ratio per check here.** A failing check's counts per scan are already stored
  (`finding_occurrences`, spec 009); a series for passing checks comes with S5-2, which defines
  what the anomaly checks read.
- **No retention yet.** Rows are small, but a daily scan of a large store adds up; S5-2 fixes
  the window its baselines need, and the clean-up job then trims to it (backlog).
- The role matrix has 34 workspace operations now (spec 022 counted 33).
- **No `scan_id` anchor** as the score history has: the page is about the column, not about
  one scan, and shows the newest scans.

## Out of scope

- Thresholds, anomalies and drift on these series: S5-2, S5-3. Charts with thresholds on the
  column view and anomalies as findings: S5-4.
- Measures per check; a row-count series per table without a column.
- Backfilling history from stored reports of earlier scans.
