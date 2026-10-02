# Spec 004 — API: connections, scans and persistence

Sprint 1, story S1-4. Depends on: specs 002, 003; ADR-0003, ADR-0006, ADR-0009.
Packages: `api/`.

## Goal

The API registers connections from `SAHIFA_CONN_*` variables, accepts scans on a connection
or on uploaded files, runs them in a background thread, persists the report and its findings
in Postgres, and serves scans, reports and findings.

## User story

As a data engineer, I upload three CSV exports or pick the `shop` database and come back to
a report that is still there tomorrow.

## Interface

| Method and path | Request | Response |
|---|---|---|
| `GET /healthz` | | `200 {status: "ok"|"degraded", database: "ok"|"unavailable", version}` |
| `GET /api/version` | | `{version, commit, schema_revision}` |
| `GET /api/connections` | | `{items: [Connection]}` |
| `POST /api/connections` | `{name, kind: "postgres"|"duckdb", secret_ref, config}` | `201 Connection`; `422` when `secret_ref` does not start with `SAHIFA_CONN_` or the variable is unset |
| `GET /api/connections/{id}` | | `Connection` or `404` |
| `POST /api/connections/{id}/test` | | `{ok, assets, error}` |
| `POST /api/scans` | `{connection_id, assets?: [str], sample_rows?: int}` | `202 Scan` |
| `POST /api/scans/upload` | multipart `files` (1–`SAHIFA_MAX_UPLOAD_FILES`), `sample_rows?` | `202 Scan`; `413` too large; `415` extension; `422` no files |
| `GET /api/scans` | `limit` (≤ 100, default 25), `cursor` | `{items: [Scan], next_cursor}` |
| `GET /api/scans/{id}` | | `Scan` |
| `GET /api/scans/{id}/report` | | `ScanReport` JSON; `409` while not succeeded |
| `GET /api/scans/{id}/findings` | `severity`, `dimension`, `asset` | `{items: [Finding]}` |

`Connection`: `id, name, kind, config, secret_ref, available, created_at`.
`Scan`: `id, connection_id, connection_name, status, created_at, started_at, finished_at,
error, sample_rows, score {overall, low, high} | null, findings {critical, high, medium, low},
assets_count`.

Tables (migration `0001_initial`):

- `connections(id uuid pk, name text unique, kind text check, config jsonb, secret_ref text
  null, created_at timestamptz)`; `kind` in (`postgres`, `duckdb`, `upload`).
- `scans(id uuid pk, connection_id fk, status text check, sample_rows int, options jsonb,
  created_at, started_at, finished_at, error text, score jsonb, finding_counts jsonb,
  assets_count int, report jsonb, report_version int)`; index `(created_at desc, id)`.
- `findings(id uuid pk, scan_id fk on delete cascade, check_type text, asset text, column_name
  text null, dimension text, severity text, evaluated bigint, failed bigint, ratio double,
  low double, high double, summary text, next_step text, evidence jsonb)`; indexes
  `(scan_id, severity)`, `(check_type)`.

Settings (env, `SAHIFA_` prefix): `ENV`, `DATABASE_URL`, `MIGRATION_DATABASE_URL`,
`DATA_DIR`, `SAMPLE_ROWS`, `MAX_UPLOAD_MB`, `MAX_UPLOAD_FILES`, `UPLOAD_TTL_DAYS`,
`MAX_CONCURRENT_SCANS`, `DUCKDB_MEMORY`, `STATEMENT_TIMEOUT_S`, `ACCESS_GATE`, `PUBLIC_URL`,
`LOG_LEVEL`, `COMMIT`.

## Behaviour

1. On start: migrate (`python -m sahifa.db.migrate upgrade head`, in the image entrypoint),
   check the schema revision (exit 3 on mismatch), mark `running` and `queued` scans
   `failed` with "interrupted by a restart", and upsert a connection for every
   `SAHIFA_CONN_<NAME>` (name lower-cased, kind from the URL scheme).
2. In `prod`, start-up refuses placeholder passwords in `DATABASE_URL` and any
   `SAHIFA_CONN_*`, and refuses `ACCESS_GATE` unset (ADR-0010).
3. Upload: files are streamed to `DATA_DIR/uploads/<scan id>/<random>.<ext>` with the size
   limit enforced while streaming; the original names are kept in the scan options for
   display only; an `upload` connection is created per scan.
4. A scan is inserted `queued`, then run by the scan runner in a thread under a semaphore of
   `MAX_CONCURRENT_SCANS`; status moves to `running`, then `succeeded` with the report,
   score, counts and findings rows written in one transaction, or `failed` with the error.
5. Credentials are read from the environment at scan time only and never logged or returned.
6. Logs are structlog JSON; every scan log line carries `scan_id`.

## Acceptance criteria

- [ ] Uploading the faulty shop's five CSVs yields a succeeded scan whose report equals the
      CLI's report for the same files and seed (except ids and times).
- [ ] With `SAHIFA_CONN_SHOP` set to the test Postgres holding the shop, `GET
      /api/connections` lists `shop`, and a scan of it succeeds.
- [ ] Oversized upload → 413, `.exe` → 415, no files → 422; nothing is written for them.
- [ ] A restart while a scan runs leaves it `failed` with "interrupted by a restart".
- [ ] `alembic check` passes (models and migration agree).

## Test cases

`api/tests/test_health.py`, `test_settings.py` (prod guard), `test_uploads.py` (limits),
`test_scans_api.py` (upload round trip, list pagination, findings filter, report 409 while
running), `test_connections.py` (env registration, `secret_ref` validation, test endpoint),
`test_migrations.py`. Database tests run when `SAHIFA_TEST_DATABASE_URL` is set; the Postgres
source tests when `SAHIFA_TEST_SOURCE_URL` is set.

## Out of scope

Persisted checks (006), the worker (007), findings across scans (008), sign-in (sprint 4).
