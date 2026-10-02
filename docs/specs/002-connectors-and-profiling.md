# Spec 002 — Connectors, sampling and column profiles

Sprint 1, story S1-2. Depends on: ADR-0001, ADR-0002, ADR-0006; domain model "Profile".
Packages: `core/`.

## Goal

Given a list of files, a directory, a `.duckdb` file or a Postgres URL, the core lists the
assets, draws a reproducible sample per asset, and returns a profile per column with counts,
statistics, top values, patterns, an inferred role and an inferred semantic type.

## User story

As a data engineer, I point Sahifa at a folder of exports or a schema and see, per column,
what is in it, before any check runs.

## Interface

```python
from sahifa_core.connectors import open_source          # -> Connector (context manager)
src = open_source(["data/"]) | open_source("postgresql://u:p@h/db?schemas=public,sales")
src.dialect            # "duckdb" | "postgres"
src.list_assets()      # list[AssetRef(namespace, name, kind)]
src.describe(asset)    # AssetInfo(columns=[ColumnInfo(name, position, physical_type, logical_type)],
                       #   primary_key, unique, foreign_keys, not_null, row_estimate)
from sahifa_core.profile import profile_asset
profile_asset(src, asset, sample_rows=100_000, seed=42)  # -> AssetProfile
```

- Source strings: a path to a file (`.csv`, `.tsv`, `.parquet`, `.json`, `.jsonl`,
  `.ndjson`), a directory (all such files, one asset per file, name = file stem), a glob, a
  `duckdb:///path/to.duckdb` URL (its tables and views), or a `postgresql://` URL with an
  optional `schemas=` query parameter (default: every schema except `pg_*` and
  `information_schema`).
- `AssetProfile`: `ref`, `population` (N), `population_exact`, `sample_rows` (n), `sampled`,
  `columns: list[ColumnProfile]`, `declared` (primary key, unique, foreign keys, not null),
  `time_series_candidate`, `error`.
- `ColumnProfile` fields as in the domain model, plus `role` and `semantic_type`,
  `semantic_share`.

## Behaviour

1. Postgres sessions are read-only with `statement_timeout`, `lock_timeout` and
   `application_name = sahifa/<scan id>` (ADR-0006); connection errors raise
   `SourceError` with the message, never the URL's password.
2. The sample is drawn once per asset: DuckDB `USING SAMPLE reservoir(n ROWS) REPEATABLE
   (seed)` into a temporary table; Postgres `TABLESAMPLE BERNOULLI(p) REPEATABLE (seed)` with
   `p` from the row estimate (capped at 100) and `LIMIT n`, as a CTE. Assets with
   `N ≤ n` or `sample_rows = 0` are read in full.
3. One aggregate query per asset computes counts and statistics for every column; one grouped
   query per text column fetches up to 1,000 most frequent values for top values, patterns
   and semantic inference (patterns are computed in Python from those values, weighted by
   count).
4. Roles are inferred as in the catalogue's preamble; semantic types are the validator with
   the highest share ≥ 0.8 among non-null fetched values (ties: the more specific type).
5. A failure in one asset sets `error` on its profile; the others continue.

## Acceptance criteria

- [ ] On the synthetic shop (spec 003 `synth`), profiles match the generator's truth: row
      counts, null counts, distinct counts of keys, the `iban` and `email` semantic types,
      roles of `id` and `customer_id`.
- [ ] The same tables loaded into Postgres give the same profile (counts equal, statistics
      within 1e-9 relative) when read in full.
- [ ] A sample of 1,000 rows from a 10,000-row table is reproducible with the same seed.
- [ ] No SQL text contains a value from the data (asserted by a test with a malicious value
      `'); DROP TABLE x; --` in a column name and in a value).

## Test cases

Unit (`core/tests/test_profile.py`): `test_profile_counts_shop`, `test_roles`,
`test_semantic_types`, `test_patterns`, `test_sample_reproducible`,
`test_quoting_hostile_names`. Integration (`core/tests/test_postgres.py`, runs when
`SAHIFA_TEST_SOURCE_URL` is set): `test_postgres_profile_equals_duckdb`,
`test_postgres_read_only`.

## Out of scope

S3 paths and credentials (R2, sprint 7), Snowflake and BigQuery (sprint 7), approximate
distinct counts above 1 M sampled rows (sprint 3 performance work).
