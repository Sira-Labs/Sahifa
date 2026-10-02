# Spec 003 — The R1 checks, scoring with intervals, the report and the CLI

Sprint 1, story S1-3. Depends on: spec 002, ADR-0004, ADR-0005, `docs/checks/catalogue.md`.
Packages: `core/`.

## Goal

`run_scan(source)` profiles every asset, generates the 20 R1 checks, evaluates them in one
query per asset (plus Python checks on grouped values), scores six dimensions with 95 %
intervals at column, asset and store level, and returns a `ScanReport`. `sahifa scan` prints
it; `sahifa synth` writes a faulty shop dataset (and its clean twin) for demos and tests.

## User story

As a data scientist, I run `sahifa scan exports/` and get a score per dimension with its
interval and a list of findings that say what is wrong, where, and what to do next.

## Interface

```python
from sahifa_core.scan import run_scan, ScanOptions
report = run_scan(["exports/"], ScanOptions(sample_rows=100_000, seed=7))  # -> ScanReport
report.model_dump(mode="json")
```

`ScanReport` (Pydantic, `report_version = 1`): `scan_id`, `started_at`, `finished_at`,
`source {kind, label}`, `options`, `score {overall, low, high, dimensions: {name: {value,
low, high, checks}}}`, `assets: [{ref, population, sample_rows, sampled, score,
dimensions, columns: [ColumnProfile + score], checks: [CheckResult], error}]`,
`findings: [Finding]`, `health: [HealthItem]`, `proposed: [CheckResult]`, `stats`.

CLI:

```
sahifa scan SOURCE... [--sample-rows N] [--all-rows] [--seed N] [--json | --pretty] [--out FILE]
sahifa synth DIR [--clean] [--rows N] [--format csv|parquet] [--seed N]
sahifa checks            # the catalogue: id, dimension, kind, severity, release
```

Exit codes: 0 scanned, 2 usage error, 3 source error.

## Behaviour

1. Checks are generated per the catalogue's "Applies to" rules; rules start `active`,
   baselines `proposed` (ADR-0005). Foreign-key inference considers every asset in the scan.
2. One evaluation query per asset with one `SUM(CASE …)` per SQL check and the matching `n`
   per check; Python checks run on `(value, count)` groups.
3. For each failing check (`k > 0`), up to five examples are fetched with counts; personal
   semantic types are masked.
4. Scores follow the domain model "Scoring (v1)"; only `active` checks count.
5. A finding is created when `ratio < 1 − max_fail_ratio`; it carries `summary`,
   `next_step`, `examples`, `sql`, the interval and the severity.
6. Health items `store.empty_table`, `store.no_primary_key` (Postgres), and
   `store.numbers_as_text` are reported.
7. `synth` writes `customers`, `orders`, `invoices`, `events` and `products` with these
   faults: null and blank emails, invalid IBANs, a malformed VAT ID, whitespace in city
   names, casing variants of cities, orphan `orders.customer_id`, duplicate order ids,
   identical duplicate rows, negative and extreme amounts, future and year-1900 dates,
   `shipped_at < ordered_at`, a stale `events` table, a numeric text column with letters, a
   non-printing character. `--clean` writes the same tables without faults.

## Acceptance criteria

- [ ] Every R1 check produces at least one finding on the faulty shop, and the clean shop
      produces no finding from any `active` check.
- [ ] A full read gives zero-width intervals; a 10 % sample gives intervals that contain the
      full-read value for every dimension in at least 19 of 20 seeds.
- [ ] Every score is within [0, 100]; a store with all checks passing scores 100.
- [ ] `sahifa scan` on the faulty shop prints the report in under 10 seconds.
- [ ] The report validates against its Pydantic model after a JSON round trip.

## Test cases

Unit (`core/tests/`): `test_score.py` (Wilson, finite-population correction, product and
delta method, aggregation weights), `test_checks.py` (one test per R1 check on the faulty
shop and one on the clean shop), `test_semantics.py` (IBAN, VAT, email, phone, country,
currency, postcode validators with valid and invalid cases), `test_scan.py` (report shape,
coverage of intervals over seeds), `test_cli.py` (exit codes, JSON output).

## Out of scope

Persisted checks and their lifecycle actions (spec 007), history-based checks (sprint 5),
explanations of clusters (sprint 6).
