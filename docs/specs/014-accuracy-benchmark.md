# Spec 014 — Accuracy benchmark per check

Sprint 3, story S3-4. Depends on: spec 003 (checks, scoring, synthetic shop), spec 007 (saved
checks and their lifecycle), ADR-0004 (95 % intervals), ADR-0005 (baselines are proposed until
approved). Packages: `core/` (synthetic shop, benchmark, CLI), `docs/`.

Status: approved 2026-10-07 by the owner; done.

## Goal

Today one test shows that each R1 rule check fires somewhere on the faulty shop, and another
shows that the clean twin has no findings. Neither says how well a check works:
- whether it finds every fault that was put in;
- whether it counts the right number of rows;
- whether it flags rows nobody broke;
- what a locked baseline does on new data that is legitimate;
- whether the 95 % interval of a sampled scan really holds the true share.

When this spec is done, a command answers these questions for each of the 20 R1 checks. It
runs over many seeds against a list of the faults that are known to be in the data. The
result is a table in `docs/checks/catalogue.md`.

## User story

As a data owner deciding whether to trust Sahifa, I can read for each check how often it finds
a known fault and how often it raises a false alarm on clean data, so that I know which
findings to act on straight away and which to read with care.

## Interface

### Fault list of the synthetic shop

`sahifa_core.synth.shop_tables(*, clean=False, drift=False, rows=10_000, seed=7, now=None)`
returns the tables in memory and the list of faults they contain:

```python
@dataclass(frozen=True)
class Fault:
    check: str          # "sah.foreign_key"
    asset: str          # "orders"
    column: str | None  # "customer_id"; None for asset-level checks
    rows: int           # rows that carry the fault in the final data; 1 for an asset-level fault
```

- **Counted from the final data.** The list is computed after every fault is written, by a
  plain Python predicate per fault. One fault can therefore overwrite another without the list
  going wrong. Side effects are counted too: for example, duplicated order keys leave some
  invoices pointing at an order id that no longer exists.
- **Shared rows.** A row can carry faults for several checks. For example, `N/A` in `email` is
  both a placeholder (`sah.not_blank`) and a bad email (`sah.semantic_format`).
- **`write_shop`** keeps its signature and output (the same CSV files). It gains `drift=False`.
  The fault list is never written into the directory, because a scan would read it as an asset.

The shop comes in three forms:

| Form | What it holds | Measures |
|---|---|---|
| Faulty (`clean=False`) | Today's faults for the 15 R1 rule checks | Rule checks |
| Clean twin (`clean=True`) | No faults | False alarms |
| Drift twin (`drift=True`) | The clean twin plus one fault per R1 baseline check | Baseline checks |

The drift twin's faults, on columns where the clean twin's baselines apply:
- **accepted values:** an order status that was never seen;
- **pattern:** SKUs in a new shape;
- **length:** customer names longer than any before;
- **range:** negative order amounts;
- **freshness:** all events moved 30 days into the past.

### Benchmark

```
sahifa bench-accuracy [--seeds 20] [--rows 5000] [--sample-rows 500] [--json]
```

It prints the table as Markdown, or as JSON with `--json`. It runs on DuckDB files in a
temporary directory and needs no database. For each seed it runs:

| Run | Data | Saved checks | Measures |
|---|---|---|---|
| A | Faulty shop, full read | none | Rule checks: detection, count match, unexpected flags |
| B | Clean twin, full read | none | Rule checks: false alarms |
| C | Drift twin, full read | baselines from a clean-twin scan, locked | Baseline checks: detection, count match |
| D | Clean twin of another seed (`seed + 10_000`), full read | the same locked baselines | Baseline checks: false alarms on legitimate new data |
| E | Faulty shop, sampled at `--sample-rows`, with the seed as sample seed | none | Sampled detection, interval coverage |

### Measures per check, summed over seeds

| Column | Definition |
|---|---|
| Faults | Fault groups put in (seed × asset × column), and the rows they hold |
| Detected | Share of fault groups where the check counted at least one failing row (runs A and C) |
| Count exact | Share of fault groups where the check's failing count equals the fault's `rows` |
| Unexpected | Checks on the faulty shop (run A) that count failing rows on an asset or column with no fault for them |
| Clean false alarms | Findings, and failing rows per evaluated row, on the clean twin (run B) |
| Baseline false alarms | Findings on a clean shop of another seed against locked baselines (run D) |
| Sampled detected | Detection in run E |
| Interval coverage | In run E, the share of fault groups on sampled assets whose true pass ratio (1 − `rows` / population) lies inside the reported 95 % interval |

A failing count is measured whether or not it raises a finding. For example, `sah.not_null` on
an optional column counts nulls but has no threshold to raise a finding. The benchmark measures
the detector; the thresholds belong to the owner (spec 007).

## Behaviour

1. **Runs.** `bench-accuracy` writes each shop form into its own temporary directory, runs A–E
   per seed, and deletes the directories afterwards. The shop's `now` is the time the benchmark
   starts, so freshness and future dates are measured against the scan's own clock.
2. **Matching.** A result matches a fault by check type, asset name and column. Asset-level
   checks match by asset alone.
3. **Locked baselines.**
   - Run C locks every baseline check that a scan of the clean twin proposed. These are the
     checks an owner would approve.
   - Run D evaluates the same locked checks on a clean shop with other random values.
4. **Same numbers every time.** The data, the sample and the scan are all seeded, so the same
   options always give the same table.
5. **Exit codes.** `0` on success; `2` on bad options (`--seeds < 1`, `--rows < 2500`,
   `--sample-rows < 1`). Below 2,500 rows, products have fewer than the 50 rows a baseline
   needs.
6. **What a bad result leads to.**
   - A rule check that misses a fault on a full read, or raises a false alarm on the clean
     twin, has a bug. The bug is fixed in this spec.
   - Count deviations, baseline false alarms on new data and misses in sampled scans are
     results. The table records them with a reason, and follow-ups go to `TASKS.md`. Tuning
     thresholds or baselines changes behaviour and needs its own spec.

## Acceptance criteria

- [x] **Fault list:** each of the 15 R1 rule checks has at least one fault in the faulty
      shop's list, and each of the 5 R1 baseline checks has one in the drift twin's. Every
      listed count equals a direct count on the written CSV files.
- [x] **Full-read detection:** on runs A and C, every R1 check detects 100 % of its fault
      groups.
- [x] **Clean twin:** run B has no findings and no failing rows for any check.
- [x] **The command:** `sahifa bench-accuracy` with its defaults runs in under 10 minutes on
      2 vCPU and prints the table.
- [x] **The table:** `docs/checks/catalogue.md` has an "Accuracy" section with the table for
      the default run (20 seeds, 5,000 rows, a 500-row sample). It covers all 20 R1 checks and
      states the command, the date and the commit. Every check below 100 % on any measure has a
      reason in the table.
- [x] **Coverage of the intervals** in sampled runs is reported; if it falls below 90 %, a
      follow-up is in `TASKS.md`.
- [x] `make lint` and `make test` pass.

## Test cases

- **Core, `tests/test_accuracy.py`:**
  - `test_fault_list_counts_match_the_files`: write all three forms; recount each fault from
    the CSV files with the standard library.
  - `test_every_r1_check_has_a_fault`: the 15 rule checks in the faulty shop's list and the 5
    baseline checks in the drift twin's.
  - `test_benchmark_small_run`, with 2 seeds, 2,500 rows and a 300-row sample:
    - detection 1.0 for every R1 check in runs A and C;
    - no findings and no failing rows in run B;
    - runs E and D are reported, with no threshold asserted;
    - the Markdown table has one row per R1 check.
  - `test_bench_accuracy_cli_rejects_bad_options`: exit code 2.
- **Existing tests:** `test_checks.py` keeps passing with the unchanged `write_shop`.

## Implementation notes

- **Result** (20 seeds, 5,000 rows, 2 CPUs, 2 min 49 s):
  - On a full read, every R1 check finds 100 % of its fault groups with the exact count, and
    flags nothing else. The clean twin has no findings and no failing rows.
  - Locked baselines raise findings on legitimate new data: `range` in 122 of 200 cases,
    `length` in 9 of 260.
  - Interval coverage in sampled scans is 85–100 %.

  The table and its reading are in `docs/checks/catalogue.md`.
- **Minimum rows is 2,500, not 500.** Products are rows / 50 and need 50 rows for a baseline,
  and the drift twin's pattern fault is on `products.sku`. Behaviour 5 is edited with this
  reason.
- **Length fault on customer names, not product titles.** A product title gets a new shape as
  well as a new length, so `sah.pattern` would flag it too. Customer names have a length
  baseline and no pattern baseline, so the fault reaches `sah.length` alone. The drift twin
  list above is edited.
- **Sample seed per seed.** The shop's faults sit at fixed rows. With one sample seed for all,
  the same rows were always drawn: a future date in row 1 was found in 100 % of seeds, a
  default date in row 2 in 0 %. Run E is edited to say so.
- **Locked, not active.** An active generated baseline takes the parameters of each new scan
  (spec 007), so it can never see drift; the benchmark locks what the clean twin proposed.
- **Coverage below 90 % for `not_blank`** (17 of 20). The follow-up is in `TASKS.md`, as the
  acceptance criteria require. The `range` false alarms go to sprint 5, where baselines are
  learnt from several scans.

## Out of scope

- Baselines learnt from several scans (seasonality, tolerance): R2, sprint 5 (S5-1, S5-2).
- Fault detection for R2 and R3 checks: their own specs. The table grows with them, as gate G3
  requires.
- Accuracy on Postgres. Checks render the same SQL through `sql.py`, and the Postgres tests
  cover the dialect.
- Matching faults to individual rows. The benchmark compares counts, because checks report
  counts and examples, not row ids.
