# System architecture

## Overview

```mermaid
flowchart LR
    subgraph Browser
        SPA["web: React SPA"]
    end
    subgraph Sahifa install
        WEB["sahifa-web<br/>Caddy: static SPA, /api proxy"]
        API["sahifa-api<br/>FastAPI"]
        WRK["sahifa-worker<br/>same image, role=worker (spec 008)"]
        DB[("sahifa-db<br/>PostgreSQL 17<br/>metadata, profiles, results")]
        UP[("uploads<br/>volume or S3 bucket")]
    end
    subgraph Customer stores (read-only)
        PG[("Postgres")]
        FILES[("CSV / Parquet / JSON<br/>local or S3")]
        WH[("Snowflake, BigQuery (R2)")]
    end
    TBY["tabayyun_core wheel<br/>(time-series hand-off, R2)"]

    SPA --> WEB --> API
    API --> DB
    WRK --> DB
    API --> UP
    WRK --> UP
    WRK -- "SQL pushdown" --> PG
    WRK -- "DuckDB" --> FILES
    WRK -- "SQL pushdown" --> WH
    WRK -.-> TBY
```

Three deployable pieces, as in Tabayyun: one API image (which is also the worker), one web
image, one Postgres. The core is a Python library inside the API image; it holds every rule
about profiling, checks and scoring and has no web or database dependency of its own.

## Components

### 1. `sahifa_core` (Python library, `core/`)

The engine. Pure functions plus connectors; no FastAPI, no ORM.

| Module | Responsibility |
|---|---|
| `connectors/` | `Connector` protocol: `list_assets()`, `columns(asset)`, `row_count(asset)`, `query(sql) -> rows`, `dialect`, `sample_from(asset, n)`. Implementations: `DuckDBConnector` (in-memory DuckDB over files and S3 paths, or a `.duckdb` file) and `PostgresConnector` (psycopg 3, read-only transaction, `statement_timeout`). Snowflake and BigQuery in R2. |
| `sql.py` | Builds every query once in DuckDB's SQL dialect and transpiles it with SQLGlot to the connector's dialect (ADR-0001). Quotes identifiers; never interpolates values. |
| `profile.py` | One aggregate query per asset for counts and statistics, one grouped query per column for top values and patterns; turns rows into `ColumnProfile`. |
| `semantics/` | Rule packs: validators for email, URL, UUID, IBAN (ISO 13616 mod-97), EU VAT formats, ISO 3166 country and ISO 4217 currency codes, E.164 phone numbers, German postcodes. Each validator is a pure function on one value. |
| `checks/` | The catalogue: each check type is a class with `applies_to(profile)`, `generate(profile) -> params`, and either `predicate(column) -> SQL` (a fail predicate evaluated in the database) or `evaluate(values) -> (n, k)` (evaluated in Python on grouped values, for checksums). |
| `scan.py` | Orchestration of one scan: discover assets → sample → profile → generate checks (or take the saved ones) → evaluate → score → report. Synchronous, so it runs in a thread or a worker process. |
| `score.py` | Wilson intervals, finite-population correction, the aggregation rules of the domain model. |
| `report.py` | The `ScanReport` data structure (Pydantic models) that the API stores and the web renders. |
| `cli.py` | `sahifa scan <source>`, `sahifa synth <dir>`, `sahifa checks`: the same engine from a terminal. |
| `synth.py` | A small shop dataset (customers, orders, invoices, events) with injected faults for demos and tests. |

### 2. `sahifa` API (Python, `api/`)

FastAPI with Pydantic v2, SQLAlchemy 2 async and Alembic on PostgreSQL 17, structlog JSON
logs. It owns connections, scans, results, findings and the check lifecycle, and calls the
core in a worker thread (`SAHIFA_SCAN_EXECUTION=inline`, the default) or through a
Procrastinate queue on the same Postgres (`queue`, spec 008, ADR-0009). In queue mode the
`sahifa-worker` process (`python -m sahifa.worker`) runs the `scans` and `maintenance`
queues: `run_scan`, the reaper every 5 minutes (scans of stalled workers fail with
"interrupted", scans left queued without a job are re-queued), the hourly upload clean-up
and, every minute, the due schedules (spec 010), which the API itself runs in inline mode.
Both modes run one shared `execute_scan`, and every scan, manual, uploaded or scheduled,
starts through one `start_scan`.

| Route group | R1 |
|---|---|
| `/healthz`, `/api/version` | liveness, version, commit, schema revision |
| `/api/connections` | list (each with its schedule summary), create (non-secret config plus `secret_ref`), read, test; `/{id}/schedule`: read, create or replace (cron, time zone, enabled; `version`), delete (spec 010) |
| `/api/scans` | create on a connection, create from uploaded files, list, read (with `trigger`: `manual` or `schedule`), report, findings (occurrences, with their finding's id and status) |
| `/api/assets` | assets stored per connection by scans, with columns and check counts (spec 007) |
| `/api/checks` | list per asset, approve, reject, lock, unlock, retire, restore, events (spec 007) |
| `/api/findings` | findings across scans: list (filter by status, severity, connection, asset; cursor), read with occurrences and events, acknowledge, resolve, mute, unmute, reopen (spec 009) |
| `/api/auth/*` | sign-in through Keycloak, BFF cookie session (spec 006, ADR-0010) |

### 3. Web (TypeScript, `web/`)

Vite + React 19 SPA with TanStack Router and Query and Tailwind v4, served by Caddy with
security headers; Caddy proxies `/api` and `/healthz` to the API (ADR-0007). Screens are in
`docs/frontend/01-frontend-design.md`.

### 4. Identity provider (sprint 2, spec 006)

Keycloak, one realm per product, Google, GitHub and passkeys, as in Tabayyun spec 013
(ADR-0010); the API is the backend-for-frontend (`sahifa.auth`). Until the realm is set up,
staging runs in `proxy` mode behind CapRover's HTTP basic auth.

## Data flow of a scan

```mermaid
sequenceDiagram
    participant U as User
    participant A as API
    participant D as sahifa-db
    participant W as Worker thread / worker
    participant S as Source store
    U->>A: POST /api/scans {connection_id} or POST /api/scans/upload (files)
    A->>D: insert scan (queued)
    A->>W: run scan id (thread, or a Procrastinate job deferred on sahifa-db)
    A-->>U: 202 {id, status: queued}
    W->>D: status running
    W->>S: list assets, row counts (read-only)
    loop per asset
        W->>S: aggregate profile query on the sample
        W->>S: grouped values for top values, patterns, semantic types
        W->>W: generate checks from the profile (or load saved checks)
        W->>S: one query: count of failing rows per check
        W->>S: examples for failing checks (≤ 5 values each)
    end
    W->>W: score with intervals, build the report
    W->>D: report, results, findings, scores; status succeeded
    U->>A: GET /api/scans/{id} (polling) and /report
```

A failure in one asset is recorded in the report (`assets[].error`) and the scan continues;
a failure to connect fails the scan with the error message (credentials are never logged).

## Sampling

- `sample_rows` (default 100,000; `0` means read everything) is the number of rows per asset
  the profile and checks see. Assets at or below it are read in full.
- DuckDB: `USING SAMPLE reservoir(n ROWS) REPEATABLE (seed)`. Postgres: `TABLESAMPLE
  BERNOULLI(p) REPEATABLE (seed)` with `p` from the planner's row estimate, capped by
  `LIMIT n`. The seed is the scan id, so a scan can be reproduced.
- Each query runs on the sample, materialised once per asset as a temporary view in DuckDB
  or as a CTE in Postgres.
- `N` (population) is the exact `count(*)` when it is cheap (files, Postgres tables under
  10 M rows by estimate) and the planner estimate above that; the report says which.

## Storage layout

| Data | Where | Kept |
|---|---|---|
| Connections, scans, checks, results, findings, scores | `sahifa-db` (Postgres 17), relational tables | until deleted |
| Scan report (profiles, results, evidence) | `scans.report` (`jsonb`) | with the scan |
| Uploaded files | `SAHIFA_DATA_DIR/uploads/<batch>/` (a volume shared by api and worker; S3 in R3) | 7 days after the scan finished by default (`SAHIFA_UPLOAD_TTL_DAYS`), then deleted by the hourly `clean_uploads` job |
| Source data | stays in the source | never copied |

## Deployment shapes

1. **CapRover** (the Sira family servers): `sahifa-db`, `sahifa-api`, `sahifa-web` and, once
   queue mode is on, `sahifa-worker` (sharing the api's `/data` volume), staging with the `-stg` suffix (ADR-0012, `deploy/caprover.md`).
2. **Docker compose** on any host: `deploy/compose.yaml` with Caddy TLS.
3. **CLI only**: `uvx sahifa-core scan ./data/` for a one-off report without a server.

## Cross-cutting

- **Security:** no secrets in code or config; connection credentials are env references
  (ADR-0006); prod refuses placeholder secrets; read-only source access; uploads limited in
  size (while the body streams), count, extension and content, stored under random names;
  identifiers quoted by SQLGlot, values never interpolated; example values of personal
  semantic types masked; security headers at the edge and on the API; rate limits per session
  or address; vulnerability and licence audits fail CI. The checklist with evidence is
  `docs/security/baseline.md` (spec 012).
- **Observability:** structlog JSON with `scan_id` and `asset` on every line; `/healthz`
  reports the database and the connected workers by commit (connections named
  `sahifa-worker/<commit>` in `pg_stat_activity`); errors to GlitchTip on the staging-and-tools server
  (ADR-0012) from R2.
- **Performance budget (R1):** a 1,000-table Postgres schema with a 100k-row sample per
  table in under 10 minutes on 2 vCPU; one aggregate query plus one check query per asset,
  plus one grouped query per text column with a semantic candidate.
- **Testing:** core unit tests on DuckDB in memory; Postgres integration tests when
  `SAHIFA_TEST_DATABASE_URL` is set (CI provides one); every check has a synthetic-fault
  test that it fires and a clean-data test that it does not.
