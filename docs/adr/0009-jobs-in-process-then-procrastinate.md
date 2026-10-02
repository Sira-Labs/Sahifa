# ADR-0009: Scans run in a thread first, in a Procrastinate worker from sprint 2

- **Status:** Accepted
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

A scan takes seconds for an upload and minutes for a schema. Tabayyun runs a Procrastinate
worker (Postgres as the queue, no broker; its ADR-0004 and spec 002) with the same image in
`role=worker`.

## Decision

- **Release 0.1, sprint 1:** the API runs a scan in a background thread (`anyio.to_thread`),
  at most `SAHIFA_MAX_CONCURRENT_SCANS` (default 2) at once; scans left `running` by a restart
  are marked `failed` with "interrupted" at start-up.
- **Sprint 2 (spec 008):** Procrastinate on the same Postgres, a `sahifa-worker` app from the
  API image with `SAHIFA_ROLE=worker`, transactional enqueue, the stale-run reaper and
  scheduled scans, exactly the Tabayyun pattern.

## Consequences

- Until sprint 2 the API container's memory must cover DuckDB scans (`SAHIFA_DUCKDB_MEMORY`,
  default 1 GB).

## Update 2026-10-02 (spec 008)

- Enqueueing is not transactional: the API commits the scan as `queued`, then defers the job
  on Procrastinate's own connection pool and stores `scans.job_id`. A failed defer marks the
  scan failed; the reaper re-queues `queued` scans left without a live job. This keeps the
  SQLAlchemy session and Procrastinate's psycopg pool apart.
- `SAHIFA_SCAN_EXECUTION` chooses: `inline` (the default, the sprint 1 thread) or `queue` (the
  worker). Inline stays until the owner creates the worker app.
- Procrastinate is pinned (3.10.0); migration 0004 carries its schema as released, and a newer
  version arrives with its own migration.
- Scheduled scans (spec 010) use the periodic tasks of the same app.
