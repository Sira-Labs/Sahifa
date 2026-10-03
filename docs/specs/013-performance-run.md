# Spec 013 — Performance run on a 1,000-table schema

Sprint 3, story S3-2. Depends on: spec 002 (connectors, profiling), spec 003 (checks, scan),
spec 004 (scan runner), ADR-0001 (SQL pushdown), ADR-0006 (read-only sources).
Packages: `core/` (scan, checks, Postgres connector, benchmark generator, CLI), `api/`
(settings), `docs/`.

Status: approved 2026-10-03 by the owner.

## Goal

The architecture sets a performance budget. This spec makes it measurable, meets it, and
records the numbers.

**The budget:** a 1,000-table Postgres schema, sampled at 100,000 rows per table, is scanned
in under 10 minutes on 2 vCPU.

**The query budget per asset:**
- one aggregate query for the profile;
- one aggregate query for the checks;
- one grouped query per text column with a semantic candidate.

**How it is met:**
- a reproducible benchmark schema;
- a scan that runs assets in parallel;
- checks that never run a subquery once per row;
- a query budget that tests keep.

## Measured before this spec

Measured on a local Postgres 16 with 4 vCPU (only one used), 50 tables of 20,000 rows plus a
parent table:

| | Time |
|---|---|
| Scan of the 50 tables | Not finished after 10 minutes. The foreign-key check took 30.6 s per table. |
| A table without a foreign key | 1.0 s, 14 queries |

**Foreign-key check.** It compares `CAST(parent.id AS TEXT) = CAST(child.col AS TEXT)` inside
`NOT EXISTS`, inside a `CASE`, inside the batched aggregate. Postgres therefore runs it as a
subplan per sampled row. The cast also hides the parent's index, so each subplan scans the
parent: O(sample × parent). A 100,000-row sample against a parent with 1 million rows would not
finish at all.

**With the foreign-key check in its own query** (prototype): 44 s for the 51 tables, 0.85 s per
table. 93 % of that is database time:

| Query | Share | Note |
|---|---|---|
| Profile aggregate | about two thirds | Of which regex shares on text columns 55 %, `count(DISTINCT)` 15 % and `trim` 20 % |
| Top values | 16 % | |
| Examples | 8 % | |

Extrapolated, 1,000 tables of mixed size would take more than 20 minutes run one after the
other.

## User story

As the operator of a warehouse with a thousand tables, I can run a nightly scan that finishes
in minutes on a small server, so that Sahifa fits next to the database instead of needing its
own machine.

## Interface

### Benchmark schema

`sahifa bench-schema <postgresql-url> [--schema bench] [--mix 700x10000,270x100000,30x1000000]`
creates the schema server-side with `generate_series`:
- **Tables:** 1,000 by default, plus a parent table `customers` with 100,000 rows. The default
  mix has 64 million rows in all.
- **Columns:** ten per table: integer key, foreign key, email, amount, status, country,
  timestamp, flag, md5 note and bucket.
- **Faults:** nulls, a negative amount, orphan keys (the foreign key is `NOT VALID`) and
  duplicated emails.

It writes, so it only ever targets a benchmark database named by the operator, never a source.
It replaces a schema only when that schema carries its marker comment, and then drops only the
tables it marked itself, without `CASCADE`: anything else in the schema, or a view elsewhere that
reads a benchmark table, makes it refuse.

### Scan options

| Name | Default | Meaning |
|---|---|---|
| `ScanOptions.workers`, CLI `--workers`, `SAHIFA_SCAN_WORKERS` | `2` | Assets scanned at once, each worker on its own read-only source session. `1` restores today's order. |

A scan with `workers = n` holds n source connections, all read-only with the same timeouts
(ADR-0006). The report is identical whatever `n` is: assets in the source's order, the same
samples (same seed) and the same results.

### Query budget

Per asset, at most:

| Queries | For |
|---|---|
| 3 | Metadata: columns, constraints, row estimate |
| 1 | Row count (only when the estimate is under 10 million) |
| 3 | Profile: the aggregate, top values, MAD |
| 1 | Checks: the batched aggregate |
| 1 per foreign-key check | Its own anti-join query |
| 1 per column with Python-evaluated checks | Grouped values |
| 1 | Freshness: the newest timestamp |
| 1 per failing SQL check, at most 10 per asset | Examples |

The first eight lines are the fixed part. The last line is capped so that a table full of
failures does not add a query per check.

`ScanStats` gains `queries_per_asset_max`, `queries_per_asset_mean` and `workers`; each asset in
the report gains `duration_s` and `queries`. A test on the synthetic shop asserts the budget.
The examples cap is new: past ten, failing checks get no examples (`examples_skipped`), findings
and the most severe first, and the finding says so.

## Behaviour

1. **Foreign-key check.** The check counts its failures in its own query,
   `SELECT count(*) FROM sample s WHERE domain AND NOT EXISTS (…)`, which the database runs as
   an anti-join. The parent's key is compared natively when both columns have the same logical
   type, and cast to text only when they differ. The batched aggregate keeps the check's `n`.
2. **Parallel assets.** Phase one (describe, count, sample, profile) runs on `workers`
   sessions. Phase two (checks) needs all profiles for the cross-table checks; it starts when
   phase one is done and runs on the same sessions. A failing asset is recorded as today;
   the other workers go on.
3. **Profile unchanged.** Measured on 100,000 rows, the five regexes on four text columns cost
   0.18 s, and cheap guards in front of them would save about 0.05 s (3 % of a 100,000-row
   table's time). A guard can also differ from the regex where Postgres's `\s` matches more
   than `ltrim` strips. The benchmark meets the budget without them, so the profile query stays
   as it was (see the implementation notes).
4. **Large tables.** Above 10 × the sample size, the sample stays `BERNOULLI`, because block
   sampling skews clustered tables. The count stays the planner's estimate above 10 million
   rows. The benchmark's 1-million-row tables show the cost of re-reading; the result is
   recorded in the implementation notes.
5. **Logging.** Each asset logs `asset.scanned` with its seconds, its queries and the worker.
   The scan logs `scan.stats`.

## Acceptance criteria

- [x] `sahifa bench-schema` creates the default schema of 1,000 tables plus a parent, and
      refuses to replace a schema without its marker.
- [x] The default benchmark scans in under 10 minutes with `workers = 2`, with the scan process
      and Postgres pinned to 2 CPUs (`taskset`). The before-and-after numbers are in the PR and
      in `docs/architecture/performance.md`: total time, time per tier, queries per asset, and
      database against Python time.
- [x] The foreign-key check takes linear time. A test with a parent of 50,000 rows and no
      index finishes in seconds, and its results equal the old check's on the synthetic shop.
- [x] `workers = 2` gives the same report as `workers = 1` on the synthetic shop and on a
      small Postgres schema, apart from the timings.
- [x] The query budget holds on the synthetic shop, by test, including the examples cap.
- [x] `make lint` and `make test` pass. The full benchmark runs locally; it is not part of CI.

## Test cases

- **Core:**
  - `bench.parse_mix`, and the marker refusal;
  - the foreign-key check's own query: native comparison against a cast, and the same `n` and
    `k` as before;
  - the parallel scan equals the serial scan;
  - the query budget;
  - the examples cap.
- **Core, Postgres (`SAHIFA_TEST_SOURCE_URL`):**
  - the foreign-key check against an unindexed parent of 50,000 rows, in seconds;
  - two workers on a 20-table schema.
- **API:** `SAHIFA_SCAN_WORKERS` reaches the runner.

## Implementation notes

- **Benchmark result:** 8 min 13 s with two workers and 15 min 47 s with one, on Postgres 16 and
  the scan pinned to 2 CPUs. The tables are in `docs/architecture/performance.md`.
- **Regex guards not done.** They would save about 3 % and could differ from Postgres's `\s`;
  behaviour 3 was edited, with this reason.
- **Examples cap at 10, not 5.** The synthetic shop already has six findings on two tables, so 5
  would have taken examples from the demo report. Findings come before proposals, then
  severity.
- **Parallel sessions on Postgres only.** DuckDB keeps each sample as a temporary table of its
  one connection, and runs each query on all its own threads.
- **Same report whatever the number of workers,** apart from values measured against the scan's
  start time: freshness age and future dates. A test on a small schema runs both within
  seconds, so they match exactly.
- **Native foreign-key comparison** when both columns share a logical type; otherwise both
  sides are cast to text. Either way the check is its own anti-join query, linear in the
  sample plus the parent.
- **Per-asset cost.** Each asset in the report has `duration_s` and `queries`, so slow tables
  are visible; `scan.stats` and `asset.scanned` log lines carry the same numbers.

## Out of scope

- Moving the sample into DuckDB to read each table once. It conflicts with pushdown
  (ADR-0001) and needs its own ADR; it would follow if the budget cannot be met otherwise.
- Snowflake and BigQuery performance: sprint 7.
- Incremental scans (only changed tables): R2.
