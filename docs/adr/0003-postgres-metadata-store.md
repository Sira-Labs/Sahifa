# ADR-0003: PostgreSQL 17 as the metadata and results store

- **Status:** Accepted
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

Sahifa stores connections, scans, profiles, check definitions, results, findings and scores.
Results are small per scan (one row per check per asset) but accumulate into a history that
R2 mines for thresholds. Tabayyun runs Postgres 17 with TimescaleDB for dense metric series;
Sahifa's history is one point per check per scan, which plain Postgres handles.

## Decision

- **PostgreSQL 17**, plain (no TimescaleDB), via SQLAlchemy 2 async with psycopg 3 and Alembic
  migrations packaged in the API wheel and applied on start (Tabayyun spec 001 pattern:
  `python -m sahifa.db.migrate upgrade head`, schema-revision guard, `/api/version` reports it).
- The **scan report** (profiles, results with evidence) is stored as `jsonb` on the scan, and
  the parts that are queried across scans (results, findings, scores) as relational rows with
  indexes on `(asset_id, check_type)`, `(scan_id)` and `(status, severity)`.
- Lists are paginated with keyset pagination on `(created_at, id)`.
- Row-level security per org arrives with tenancy in R2 (Tabayyun ADR-0007 model).

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| TimescaleDB | Compression, continuous aggregates | Timescale licence for some features; not needed at one point per scan | Revisit if metric history grows past ~100 M rows |
| SQLite | Zero ops | No concurrent worker writes, no RLS | The worker and API write at once |
| Results only as JSON files | Simple | No cross-scan queries | History is the product in R2 |

## Consequences

- One `postgres:17` app per install; backups as in ADR-0012.
- The report JSON is versioned (`report_version`) so the web can read old scans.
