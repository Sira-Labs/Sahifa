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
- **Sprint 2 (spec 007):** Procrastinate on the same Postgres, a `sahifa-worker` app from the
  API image with `SAHIFA_ROLE=worker`, transactional enqueue, the stale-run reaper and
  scheduled scans, exactly the Tabayyun pattern.

## Consequences

- Until sprint 2 the API container's memory must cover DuckDB scans (`SAHIFA_DUCKDB_MEMORY`,
  default 1 GB).
