# ADR-0002: DuckDB for files, object storage and lakehouse tables

- **Status:** Accepted
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

Gap 2 of research 02: no open tool assesses an organisation's whole estate (databases,
warehouses, lakehouse tables and object storage) in one pass; TestGen has no file or S3
support at all. Files arrive as CSV, Parquet and JSON, locally or on S3-compatible storage
(RustFS on the Sira servers), and increasingly as Iceberg and Delta tables.

## Decision

- **DuckDB** (MIT) is the engine for everything that is not a database server: uploaded files,
  local paths, `s3://` globs, and later Iceberg and Delta tables through DuckDB's extensions.
  Each file or glob becomes an asset backed by a DuckDB view (`read_csv_auto`,
  `read_parquet`, `read_json_auto`).
- DuckDB runs **in-process**, one in-memory database per scan, with `memory_limit` and
  `threads` set from configuration and the sample materialised as a temporary table.
- S3 credentials come from environment variables named by the connection (ADR-0006) and are
  set as a DuckDB `SECRET` for the scan only.
- Extensions (`httpfs`, later `iceberg`, `delta`) are **installed at image build time**; the
  runtime never downloads extensions (air-gapped installs, supply chain).

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Polars | Fast, Arrow-native | No SQL dialect shared with the database checks; S3 and Iceberg support thinner | Two implementations of every check |
| Spark (Deequ, DQX) | Scale | JVM cluster for a self-hosted single-node product | Too heavy for the target install |
| DataFusion | Rust, Apache-2.0 | Smaller ecosystem for CSV quirks and Iceberg today | Revisit if DuckDB's licence or footprint changes |

## Consequences

- One SQL dialect (DuckDB) is also the dialect queries are written in before transpiling.
- Large files are sampled with `USING SAMPLE reservoir(n ROWS) REPEATABLE (seed)`; a full read
  is opt-in (`sample_rows: 0`).
- The API image grows by the DuckDB wheel and extensions (~60 MB).
