# Spec 008 — Procrastinate worker, stale-scan reaper, upload clean-up

Sprint 2, story S2-2. Depends on: spec 004 (scan runner, uploads, `/healthz`), spec 007 (scan
persistence of checks); ADR-0009. Packages: `api/` (jobs, worker entry point, settings,
migration 0004, `/healthz`), `deploy/` (entrypoint, CapRover worker app, compose, one-click
template), `.github/` (the worker deploy already exists and is gated on its token).

Status: approved 2026-10-02 by the owner.

## Goal

Scans can run in a separate `sahifa-worker` process (the same API image with
`SAHIFA_ROLE=worker`) that takes jobs from a Procrastinate queue on the same Postgres. The
API then only records and enqueues scans, so it stays responsive and its memory no longer has
to cover DuckDB.

A reaper job finds scans whose worker died and marks them failed with "interrupted". It also
re-queues scans that were recorded but never queued. A clean-up job deletes old upload
folders. `/healthz` lists the connected workers by commit, so the deploy workflows can wait for
the new worker.

Until the owner creates the worker app, nothing changes: the default mode keeps running scans
in the API process.

## User story

As the operator, I run scans in a worker that can be restarted and scaled on its own, and
interrupted scans and stale uploads clean themselves up, so that the API stays fast and the
disk does not fill.

## Interface

### Settings (environment, prefix `SAHIFA_`)

| Name | Default | Meaning |
|---|---|---|
| `SAHIFA_SCAN_EXECUTION` | `inline` | `inline`: the API runs scans in a thread (today's behaviour). `queue`: the API enqueues a Procrastinate job and a worker runs it. |
| `SAHIFA_ROLE` | `api` | `worker` starts the Procrastinate worker instead of the HTTP server. It requires `SAHIFA_SCAN_EXECUTION=queue`; otherwise the worker refuses to start with exit code 2. |
| `SAHIFA_MAX_CONCURRENT_SCANS` | `2` | Inline: threads in the API. Queue: the worker's concurrency. |
| `SAHIFA_UPLOAD_TTL_DAYS` | `7` | Existing setting (spec 004). Upload folders whose scan finished longer ago than this are deleted. |
| `SAHIFA_REAPER_STALE_MINUTES` | `10` | A running job whose worker has sent no heartbeat for this long is treated as stalled. A queued scan with no job, older than this, is re-queued. |

### Jobs (`sahifa.jobs`, one Procrastinate app on the API's database)

| Task | Queue | When | Does |
|---|---|---|---|
| `run_scan(scan_id)` | `scans` | Deferred by `POST /api/scans` and `POST /api/scans/upload` in queue mode | Runs exactly what the inline runner does today: load saved checks, `run_scan`, persist the report and checks, mark the scan succeeded or failed. |
| `reap()` | `maintenance` | Periodic, every 5 minutes | (1) For running jobs whose worker is stalled, marks the scan failed with `interrupted: the worker stopped` and the job failed. (2) Re-queues a `queued` scan older than `SAHIFA_REAPER_STALE_MINUTES` that has no job. |
| `clean_uploads()` | `maintenance` | Periodic, hourly | Deletes upload folders of finished scans older than `SAHIFA_UPLOAD_TTL_DAYS`, and orphan upload folders older than that with no scan. Never touches a folder whose scan is `queued` or `running`. |

The scan's reports, findings and checks stay in the database. Only the uploaded files are
deleted.

### Database (migration 0004)

- Migration 0004 applies the Procrastinate schema of the pinned Procrastinate version. Its
  downgrade removes that schema.
- The Alembic environment ignores Procrastinate's objects (`procrastinate_*`), so that
  `alembic check` stays clean.
- `scans` gains `job_id` bigint null, the Procrastinate job that runs the scan in queue mode.

### `/healthz`

- `workers` lists one entry per connected worker: `{"commit": "<sha>", "connections": n}`.
- The source is `pg_stat_activity`: application names `sahifa-worker/<commit>` on the API's
  database.
- `wait-live.sh` already reads either form.

### Process

- `docker-entrypoint.sh` with `SAHIFA_ROLE=worker` runs `python -m sahifa.worker`. The worker:
  1. checks the production settings like the API does, and the schema revision is the head;
  2. if not, waits up to 5 minutes for the API to migrate, then exits 3;
  3. names its database connections `sahifa-worker/<commit>`;
  4. runs the `scans` and `maintenance` queues;
  5. on SIGTERM, finishes or abandons gracefully (Procrastinate's shutdown).
- The image healthcheck for the worker checks that the process is alive. It does not use HTTP.

## Behaviour

1. **Inline mode** behaves exactly as today. In addition, the API itself schedules the
   clean-up of uploads hourly, in a background task.
2. **Queue mode, enqueueing.**
   1. The scan row is committed as `queued`.
   2. The job is deferred with the scan id, and `scans.job_id` is stored.
   3. If deferring fails, the scan is marked `failed` with the error and the request still
      answers 202 with that scan. The reaper also catches scans left `queued` without a job.
   4. A `queueing_lock` per scan id prevents two jobs for one scan.
3. **Queue mode, running.**
   1. The worker job marks the scan `running`.
   2. It does everything the inline runner does, through the same shared function. The inline
      runner and the job call one `execute_scan(sessions, settings, scan_id)`, so there is no
      duplicated logic.
   3. It records success or failure as today.
   4. A job for a scan that is no longer `queued` is a no-op, which makes it idempotent.
4. **Start-up.** In queue mode the API no longer marks running scans `interrupted` at
   start-up; the reaper owns that. Inline mode keeps today's start-up behaviour.
5. **Uploads in queue mode** need the API and the worker to see the same `/data`. On one
   CapRover server that means one named volume mounted in both apps (`deploy/caprover.md`
   explains it). Multi-node storage (S3) is R3.
6. **Logging.** Each of these events is logged:
   - `scan.queued` (scan id, job id);
   - `scan.started`, `scan.succeeded`, `scan.failed` (as today, plus `worker` = the commit);
   - `reaper.interrupted` (count), `reaper.requeued` (count);
   - `uploads.cleaned` (folders, bytes).
7. **Security.** The worker reads sources only through the core's read-only connectors
   (ADR-0006). Upload paths are deleted only when they lie inside `uploads_dir`: the path is
   resolved and checked, and symlinks are never followed out of it.

## Acceptance criteria

- [x] In queue mode, a scan posted to the API is run by a worker started with
      `python -m sahifa.worker`, and the report matches an inline scan of the same files.
- [x] Inline mode is unchanged: the existing scan tests pass without modification.
- [x] Killing the worker during a scan, then running the reaper with a short stale time,
      marks the scan `failed` with "interrupted". A `queued` scan without a job is re-queued
      and then completes.
- [x] `clean_uploads` deletes only folders older than `SAHIFA_UPLOAD_TTL_DAYS` whose scans
      are finished, plus orphan folders. It keeps running and queued scans' folders and refuses
      paths outside `uploads_dir`.
- [x] `/healthz` lists a running worker as `{"commit", "connections"}`, and `wait-live.sh`
      accepts it (a test parses the output with the script's `jq` filter).
- [x] Migration 0004 upgrades and downgrades, and `alembic check` is clean.
- [x] `SAHIFA_ROLE=worker` with `SAHIFA_SCAN_EXECUTION=inline` exits 2 with a clear message.
- [x] Deploy docs:
  - `deploy/caprover.md` section 3 is complete: worker app, shared volume, variables, token;
  - the switch to queue mode is a checklist item for the owner;
  - `compose.yaml` has a `worker` service;
  - the one-click template offers the worker.
- [x] `make lint` and `make test` pass. Procrastinate is MIT-licensed (ADR-0008).

## Test cases

- **API (`api/tests/test_jobs.py`, database required):**
  - enqueue in queue mode, and run the job in-process (Procrastinate's worker with
    `wait=False`, or calling the task);
  - the job's idempotence;
  - a failure to defer;
  - the reaper on a stalled job (simulate by setting the job's heartbeat in the past);
  - re-queueing a `queued` scan without a job;
  - clean-up: `SAHIFA_UPLOAD_TTL_DAYS`, running scans kept, orphans, path traversal and symlink refused;
  - `/healthz` with a connection named `sahifa-worker/<commit>`;
  - worker start-up refusals (role and mode, old schema).
- **Migration:** upgrade, `alembic check`, downgrade to 0003, upgrade again.
- **Script:** the `wait-live.sh` filter on a sample `/healthz` body.

## Implementation notes

- `SAHIFA_UPLOAD_RETENTION_HOURS` dropped: the existing `SAHIFA_UPLOAD_TTL_DAYS` (default 7,
  at least 1, so no off switch) already promised this deletion and is documented (owner, 2026-10-02).
- Enqueueing commits the scan, then defers on Procrastinate's own pool (not one transaction
  with the insert); the reaper covers the gap, as behaviour 2 describes (ADR-0009 update).
- Migration 0004 carries Procrastinate 3.10.0's `schema.sql` as a file next to it (with its MIT
  notice) instead of reading the installed package, so 0004 never changes; Procrastinate is
  pinned to `==3.10.0` and a test fails on a bump, which needs a new migration.
- The reaper also re-queues a `queued` scan whose job ended without running it (not only
  `job_id` null); the queueing lock is `scan:<id>`.
- The worker prunes workers silent for `SAHIFA_REAPER_STALE_MINUTES` at start (Procrastinate's
  `stalled_worker_timeout`), so both use one threshold; their jobs are then found by the reaper.
- A job cancelled by Procrastinate (abort, or shutdown) marks its scan interrupted at once.
- Upload folders map to scans by the connection name `upload-<folder>` set at upload.
- The worker image healthcheck looks for a running `python -m sahifa.worker` in `/proc`.
- `compose.yaml` runs queue mode with a `worker` service by default; CapRover stays inline
  until the owner creates the worker app.
- The one-click worker is a second template, `deploy/caprover/one-click/sahifa-worker.yml`,
  pasted with the install's app name: a CapRover template cannot make an app optional, and a
  worker in inline mode must exit 2.

## Out of scope

- Scheduled scans per connection: spec 010, which uses Procrastinate's periodic tasks from
  here.
- S3 or another shared object store for uploads, and multi-node workers: R3.
- Retries for failed scans: a failed scan is final, and the user rescans.
- A worker metrics endpoint: sprint 3 (S3-1) or later.
