# Deployment

Two images are built by `.github/workflows/release.yml` on every push to `main` and on
`v*` tags and published to the GitHub Container Registry with provenance and SBOM. Only
`main` and `v*` tags on commits that are on `main` publish and deploy: a manual run on any
other branch does nothing, and a tag outside `main` fails the run. Tag releases from `main`.
Each image is pushed by digest, scanned with Trivy, and tagged only when no fixable CRITICAL
finding is left, so a failed scan leaves an untagged digest that nothing deploys:

| Image | Contents |
|---|---|
| `ghcr.io/sira-labs/sahifa-api` | Python API with the `sahifa_core` library (profiling, checks, scoring, DuckDB and Postgres connectors) and the Alembic migrations; also the worker (`SAHIFA_ROLE=worker`, spec 008) |
| `ghcr.io/sira-labs/sahifa-web` | Static SPA served by Caddy with security headers; proxies `/api` and `/healthz` to the API and serves `/version.json` |

Tags: `latest` (main), `main`, `sha-<short>`, and `<version>` for tags. The compose bundle
requires `SAHIFA_TAG`; promotion sets the digest-pinned images instead, so a deployment never
depends on a moving tag. Both images report the commit they were built from: the web image in
`/version.json`, the api image in `GET /api/version`.

```mermaid
flowchart LR
    B["Browser"] --> W["sahifa-web<br/>Caddy :80"]
    W -- "/api, /healthz" --> A["sahifa-api<br/>FastAPI :8000"]
    A --> D[("sahifa-db<br/>Postgres 17")]
    A --> U[("/data<br/>uploads, TTL")]
    A -- "read-only" --> S[("sources:<br/>Postgres, files")]
```

## Run on CapRover

See [caprover.md](caprover.md): three apps from the published images, TLS by CapRover, a
staging server that every push to `main` deploys, and a production server that runs the
staging-tested digest after the owner's approval (ADR-0012).

## Run on any Docker host

```bash
mkdir -p ~/sahifa && cd ~/sahifa
curl -fsSL https://raw.githubusercontent.com/Sira-Labs/Sahifa/main/deploy/compose.yaml -o compose.yaml
curl -fsSL https://raw.githubusercontent.com/Sira-Labs/Sahifa/main/deploy/.env.example -o .env
# edit .env: POSTGRES_PASSWORD (mandatory, generate with `openssl rand -hex 24`),
# SAHIFA_DOMAIN for automatic TLS, SAHIFA_PUBLIC_URL, the sign-in settings or the access
# gate (see "Sign-in" below) and one SAHIFA_CONN_<NAME> line per database to assess
docker compose up -d
```

Caddy obtains a TLS certificate automatically when `SAHIFA_DOMAIN` is set and ports 80/443
are reachable. Without a domain it serves plain HTTP on port 80 for use behind your own
load balancer.

## Sign-in, or an access gate

An install can read every source it is connected to, so with `SAHIFA_ENV=prod` the api
refuses to start unless one of two things keeps strangers out (spec 006, ADR-0010):

- **Sign-in through Keycloak** (`SAHIFA_AUTH_MODE=oidc`): Google, GitHub and passkeys through
  a realm `sahifa`; `SAHIFA_ADMIN_EMAIL` and members of a workspace get access (addresses in
  `SAHIFA_ALLOWED_EMAILS` become editors of the `Default` workspace, spec 016). The
  settings are in `.env.example`; the realm set-up is `caprover.md`, section 4a.
- **An access gate** (`SAHIFA_AUTH_MODE=proxy` with `SAHIFA_ACCESS_GATE=basic-auth-at-proxy`):
  something in front asks for a password. On CapRover that is the web app's HTTP basic auth
  (`caprover.md`, section 4a, "Interim"); on a compose host it is your load balancer or
  reverse proxy. Set the variable only after the password prompt really appears on every
  path, including `/api/version`; the variable does not protect anything by itself, it
  records a decision.

## Continuous deployment from GitHub Actions

Every push to `main` deploys to staging (`release.yml`, job `deploy-staging`); production is
promoted from staging with `promote.yml` (Actions → promote → Run workflow on `main`, with the
commit staging runs), behind the `production` environment's required reviewer. The CapRover
setup of both environments is in `caprover.md`, section 5. For a plain Docker host as the
production target, `promote.yml` ships the compose file over SSH and runs
`docker compose pull && up -d` with the promoted images pinned by digest
(`SAHIFA_API_IMAGE`, `SAHIFA_WEB_IMAGE`; manual installs use `SAHIFA_TAG`); configure the
GitHub **environment** `production` with:

| Kind | Name | Value |
|---|---|---|
| variable | `DEPLOY_HOST` | hostname or IP of the Docker host |
| variable | `DEPLOY_USER` | SSH user with permission to run docker |
| variable | `CAPROVER_WEB_URL` | the install's public address; the workflow waits until it serves the commit |
| secret | `DEPLOY_SSH_KEY` | private key for that user (use a dedicated deploy key) |
| secret | `CAPROVER_WEB_BASIC_AUTH` | `user:password` of the proxy's basic auth, so the wait step gets past it |

Repository → Settings → Environments → New environment → `production`, with the owner as
required reviewer and `main` as the only deployment branch.

The host needs Docker Engine with the compose plugin and outbound access to `ghcr.io`; the
images are public, so it pulls without logging in.

## Air-gapped installs

```bash
docker pull ghcr.io/sira-labs/sahifa-api:latest ghcr.io/sira-labs/sahifa-web:latest postgres:17
docker save ghcr.io/sira-labs/sahifa-api:latest ghcr.io/sira-labs/sahifa-web:latest postgres:17 | zstd > sahifa-images.tar.zst
# on the target host
zstd -d < sahifa-images.tar.zst | docker load
```

## Local development

`deploy/compose.dev.yaml` starts only Postgres 17 on `localhost:5432`: the metadata database
`sahifa` and an empty demo source `shop` with the read-only login `sahifa_reader`, set up as
`caprover.md` section 6 describes for a real source. Run the API and web on the host
(`uv run alembic upgrade head` once in `api/`). Load any test data into `shop` as the user
`sahifa` (for instance the CSV files `sahifa synth` writes, with `\copy`), and point the dev
API at it with
`SAHIFA_CONN_SHOP=postgresql://sahifa_reader:sahifa_reader@localhost:5432/shop?schemas=public`.
To try queue mode, start the API and, in `api/`, a worker with the same environment plus
`SAHIFA_SCAN_EXECUTION=queue` on both: `SAHIFA_ROLE=worker uv run python -m sahifa.worker`.
The core alone needs no infrastructure: `sahifa scan <dir>` runs on DuckDB in memory.

## Scans and the worker

`SAHIFA_SCAN_EXECUTION` decides where scans run (ADR-0009, spec 008):

- `inline` (the default, and the CapRover template): the api runs each scan in a background
  thread, at most `SAHIFA_MAX_CONCURRENT_SCANS` (default 2) at once, so the api container's
  memory must cover DuckDB (`SAHIFA_DUCKDB_MEMORY`, default `1GB`, per scan). Scans left
  `running` by a restart are marked `failed` with "interrupted" when the api starts again,
  and the api deletes old uploads hourly.
- `queue` (the compose bundle): the api records each scan and defers a job to a Procrastinate
  queue in its own Postgres; a `sahifa-worker` app or compose service runs it. The worker is
  the api image with `SAHIFA_ROLE=worker` and the same environment as the api plus
  `SAHIFA_SCAN_EXECUTION=queue` on both (it refuses to start otherwise, exit code 2). It never
  migrates: it waits up to 5 minutes for the api to migrate, then exits with code 3. It runs
  the scans, a reaper every 5 minutes (scans of a worker silent for
  `SAHIFA_REAPER_STALE_MINUTES`, default 10, fail with "interrupted: the worker stopped";
  scans left queued without a job are queued again), the hourly upload clean-up and, every
  minute, the due schedules of connections (spec 010; inline, the api runs them). Api and
  worker must share the uploads volume (`/data`).

The worker names its database connections `sahifa-worker/<commit>`, and `GET /healthz` on the
api lists them in its `workers` field as `{"commit", "connections"}`; the deploy workflows use
that to wait until the worker runs the new commit. CapRover: `caprover.md` section 3.

## Uploads

Uploaded files are stored under random names in `SAHIFA_DATA_DIR/uploads/<batch>/` (the
image default is `/data`; the compose bundle mounts the `data` volume there), limited by
`SAHIFA_MAX_UPLOAD_MB` (200) per file, `SAHIFA_MAX_UPLOAD_TOTAL_MB` (1024) per request,
`SAHIFA_MAX_UPLOAD_FILES` (20) and the extensions `.csv`, `.tsv`, `.parquet`, `.json`,
`.jsonl`, `.ndjson` (the content must match: Parquet's magic bytes, text without NUL bytes).
An upload that would leave less than `SAHIFA_MIN_FREE_DISK_MB` (1024) free is refused with
507. They are deleted `SAHIFA_UPLOAD_TTL_DAYS` (7)
days after their scan finished, by an hourly clean-up (in the worker, or in the api in inline
mode); folders of queued or running scans are kept. They are disposable working copies: the scan report keeps what was found, so the volume
needs no backup.

## Source connections

Each Postgres database to assess is one environment variable on the api (and the worker,
in queue mode), `SAHIFA_CONN_<NAME>`, holding a URL such as
`postgresql://sahifa_reader:<password>@host:5432/db?schemas=public,sales`. At start the api
registers a connection named `<name>` in lower case; Sahifa's database stores only that
variable's name, never the credentials (ADR-0006). Every session against a source is a
read-only transaction with a statement timeout (`SAHIFA_STATEMENT_TIMEOUT_S`, 60 s), a lock
timeout and the application name `sahifa/<scan id>`, so it is visible in the source's
`pg_stat_activity`. Grant Sahifa a login with `SELECT` only: `caprover.md`, section 6. In
prod the api refuses to start when a `SAHIFA_CONN_*` value carries a placeholder password.

## Schema migrations

The api image runs the packaged Alembic migrations to `head` on every start, before serving,
so a deployment upgrades the schema in place; the migration is idempotent and a failed one
stops the new container while the previous release keeps serving. The api refuses to serve
(exit code 3, log `db.schema_mismatch`) when the database is at a different revision than the
migrations it ships with, and `GET /api/version` reports `schema_revision`. Take a `pg_dump`
before upgrading a production database.

`SAHIFA_MIGRATION_DATABASE_URL` is optional: a separate login (the table owner) for the
migration step only. Without it migrations use `SAHIFA_DATABASE_URL`.

Row-level security (spec 016) keeps each workspace's rows apart in Postgres, so the api's login
must not bypass it. The Postgres image makes `POSTGRES_USER` a superuser, which would; migration
0008 therefore creates a role `sahifa_app` without login and lets the migrating login join it,
and the api switches to it in every transaction. A separate api login that neither owns the
tables nor is a superuser is bound anyway; it needs `SELECT`, `INSERT`, `UPDATE` and `DELETE` on
the tables. With `SAHIFA_ENV=prod` the api refuses to start (exit code 4, log
`db.rls_bypassed`) when its login would bypass row-level security.
