# Spec 021 — Install in your own environment, and what the login may do

Sprint 4b, story S4b-2. Depends on: spec 006 (sign-in and the access gate), spec 008 (worker),
spec 012 (security baseline), spec 019 (the web image), ADR-0006 (read-only access,
credentials by reference), ADR-0010 (identity). Packages: `core/` (access report, CLI),
`api/`, `web/`, `deploy/`, `.github/`, `docs/`.

Status: approved 2026-10-12 by the owner; done.

## Goal

A test user installs Sahifa on their own machine or server and assesses their own databases
and folders of files, in under 15 minutes, without Keycloak. Sahifa tells them what the
database login it was given may do. A login that can read is fine; a login that could also
write is flagged, because the read-only guarantee should come from the database role, not
only from Sahifa's read-only sessions.

## User story

As a data engineer trying Sahifa, I run a few commands, point it at a Postgres database and a
folder of Parquet files, and see a report. Sahifa tells me plainly that the login I gave it
can only read, or that it could write and how to fix that.

## Interface

### Quick start (`deploy/quickstart.md`, linked from the deploy README)

1. **Download** `compose.yaml`, `.env.example` (as `.env`) and `compose.override.example.yaml`.
2. **Fill in `.env`.**
   - `POSTGRES_PASSWORD`, generated.
   - `SAHIFA_TAG=latest` (the default of `.env.example`, built from `main`) for now; S4b-4
     switches this to a released version.
   - A password for the built-in gate (below).
   - One `SAHIFA_CONN_<NAME>` line per database or folder.
3. **Folders and databases on the host,** in `compose.override.yaml`, which compose reads
   automatically:
   - Each folder is mounted **read-only** into the api and the worker, for example
     `/home/me/exports:/sources/exports:ro`, and named in `SAHIFA_CONN_EXPORTS=/sources/exports`.
   - A database on the same machine is reached as `host.docker.internal`; the example
     declares `extra_hosts: host.docker.internal:host-gateway`.
4. **A read-only database login.** The SQL of `caprover.md` section 6 moves to a shared page,
   `docs/guides/read-only-login.md`, which both guides link.
5. **Start and check.**
   - Run `docker compose up -d` and open `http://localhost`.
   - Sign in at the password prompt.
   - On *Connections*, click *Test*: it lists what each login may do (below).
   - Start a scan.

### A password gate built into the web image

For one-person and small-team installs without Keycloak:

| Variable (web service) | Meaning |
|---|---|
| `SAHIFA_BASIC_AUTH_USER` | the user name |
| `SAHIFA_BASIC_AUTH_HASH` | a bcrypt hash from `docker compose run --rm --no-deps web caddy hash-password` |

- When both are set, Caddy asks for the password on **every** path, `/api/version` and
  `/healthz` included. The api's own health check in compose talks to the api directly, so it
  is not affected.
- The api runs with `SAHIFA_AUTH_MODE=proxy` and `SAHIFA_ACCESS_GATE=basic-auth-at-proxy`, as
  spec 006 already allows for a gate in front.
- The Caddyfile imports one of two snippets, chosen by `SAHIFA_EDGE_AUTH` (`off` by default,
  `basic` for the gate). The default keeps today's behaviour, so CapRover and staging do not
  change.
- `.env.example` documents both ways in: this gate, or sign-in through Keycloak.

### What the login may do (the access report)

A new core function, `Connector.access_report()`, returns:

| Field | Postgres | Files and DuckDB |
|---|---|---|
| `verdict` | `read_only`, `can_write`, or `unknown` (the check itself failed) | same |
| `readable` | tables and views in scope with `SELECT` | files Sahifa can read |
| `unreadable` | tables in scope without `SELECT`, which a scan will skip | — |
| `writable` | tables in scope where the login has `INSERT`, `UPDATE`, `DELETE` or `TRUNCATE` (or owns them); up to 20 names and the count | files or folders the Sahifa process may write |
| `can_create_in` | schemas in scope with `CREATE`, and the database if it has `CREATE` | — |
| `role_flags` | `superuser`, `bypassrls`, `createrole`, `createdb`, `replication`, and membership in `pg_write_all_data`, `pg_write_server_files` or `pg_execute_server_program` | — |
| `advice` | one sentence: what to change, e.g. "Revoke INSERT, UPDATE, DELETE on 3 tables; see the read-only login guide" | "Mount the folder read-only (`:ro`)" |

- **The verdict.** It is `can_write` when anything in `writable`, `can_create_in` or
  `role_flags` is present; otherwise `read_only`. `TEMP` is not counted: temporary tables
  live only in Sahifa's own session.
- **Only catalog queries.** The report reads `pg_roles`, `pg_class`, `has_table_privilege`
  and `has_schema_privilege`, with bound parameters. It never reads table data, and runs in
  the same read-only session as a scan.
- **Files.** Upload connections are Sahifa's own copies and get no report.

**Where it shows:**
- **`POST /api/connections/{id}/test`** answers with an `access` object next to `ok` and
  `assets`. The *Test* button on *Connections* shows "Read-only login" with a check mark, or
  "This login could write" with the writable count and the advice. The table names are listed
  under a "Show" toggle.
- **Every scan** stores the verdict and the counts in its report (`source_access`). A report
  from a login that could write shows a warning above the scores, with the advice.
- **The CLI.** `sahifa access <source>` prints the report and exits with 0 for `read_only`, 3
  for `can_write` and 1 for an error, so a setup script can stop on a write-capable login.

The check is advice. Scans still run with a write-capable login, in read-only sessions as
before (ADR-0006). Refusing such logins is out of scope.

### CI job `quickstart`

A job that follows the quick start on a fresh runner:
1. builds both images from the PR;
2. starts the compose bundle with the gate, an override that mounts a folder of the faulty
   shop's CSV files read-only, and a Postgres source container holding the faulty shop with
   two logins: `sahifa_reader` (read-only) and `writer` (owns a table);
3. through the gate:
   - checks that `/api/version` without a password answers 401;
   - tests the three connections and asserts the verdicts: reader `read_only`, writer
     `can_write`, files `read_only`;
   - starts a scan of the reader's database and of the folder, waits for both, and asserts
     findings;
4. checks that a scan with the writer login stores `can_write` in its report.

## Behaviour

1. **No secrets in the report.** It names roles' flags, schemas and tables, never a password
   or a value from the data.
2. **A failing check** (a catalog the login may not read) gives `verdict: unknown` with the
   reason; the test and the scan still succeed.
3. **Files.** A folder mounted `:ro` reports `read_only`; the same folder mounted writable
   reports `can_write` with the mount advice. DuckDB opens files read-only either way.
4. **The gate.** It protects the whole site. Without `SAHIFA_EDGE_AUTH=basic`, nothing
   changes. With it but without a hash, Caddy refuses to start and says which variable is
   missing.

## Also in this PR (from the spec 020 review)

- `delete_folder` contains an `OSError` while it measures a folder, so cleanup after deleting
  a workspace cannot answer 500 after its commit.
- Creating an invitation takes a transaction-scoped advisory lock on (workspace, email), so
  two admins inviting the same address at once replace each other instead of failing.

## Acceptance criteria

- [x] On a fresh runner, the quick start (CI job `quickstart`) scans a Postgres database and a
      folder of files, and flags the write-capable login (the sprint plan's "done when").
- [x] `access_report` gives `read_only` for the documented read-only login, and `can_write`
      for a login with a write grant, a `CREATE` on a schema, ownership of a table, or a role
      flag; `unknown` when the check fails.
- [x] The *Test* button and the scan report show the verdict and the advice; `sahifa access`
      exits 0, 3 or 1.
- [x] The built-in gate asks for a password on every path when on, and nothing changes when
      off (staging's headers and behaviour are unchanged).
- [x] The read-only login guide is one page, linked from the quick start and the CapRover
      guide.
- [x] The two carried review fixes have tests.
- [x] `make lint` and `make test` pass.

## Test cases

- **Core, `tests/test_access.py`** (against `SAHIFA_TEST_SOURCE_URL`, with roles created for
  the test):
  - the read-only login;
  - `INSERT` on one table;
  - `CREATE` on a schema;
  - a table the login owns;
  - a role flag;
  - `schemas=` limiting the scope;
  - a login that may not read `pg_roles` attributes, giving `unknown`;
  - files: a read-only and a writable folder (`chmod`);
  - the CLI exit codes.
- **API:** the test endpoint carries `access`; a scan report carries `source_access`.
- **Web:**
  - the *Test* button for `read_only` and `can_write` (with the names toggle);
  - the warning on a report.
- **CI:** the `quickstart` job; `caddy validate` with the gate off and on.
- **The carried fixes:** `delete_folder` on a folder whose file vanishes while it is measured;
  two concurrent invitation creates.

## Implementation notes

- **The gate's switch** is a Caddyfile `import edge-auth-{$SAHIFA_EDGE_AUTH:off}.caddy`, resolved
  when Caddy reads its config. A small start script (`sahifa-web`, the image's command) refuses
  `basic` without a user or a hash, or an unknown mode, naming the variable, before Caddy would
  fail with an error about base64.
- **Writable means "this process may write"**: `os.access(W_OK)` on each file and its folder, which
  a `:ro` mount answers with no even for root. For Postgres, write privileges count only where
  the login also has `USAGE` on the schema; ownership counts as writing.
- **Postgres 16 and CREATEROLE.** A CREATEROLE login is no longer a member of the roles it makes,
  so the tests join each role they create before handing it a table or dropping what it owns.
- **The quick-start job edits `.env` like a person would**: the variable's own line first, then a
  commented example; the example's prose no longer starts a line with `NAME=`.
- **The quick-start job found an older bug.** Compose passed `SAHIFA_DOMAIN` as an empty string
  without a domain, and Caddy uses a placeholder's default only for an unset variable, so the web
  container of the compose bundle never started without a domain (CapRover leaves it unset). The
  start script now unsets empty settings and reads the config once before `caddy run`, which
  exits on a bad config without saying why; `web-image-check.sh` starts the image with empty
  settings as compose does.
- **The full image build cannot run in this sandbox** (pnpm and uv behind a TLS-intercepting
  proxy). The final web stage and the access checks against a local Postgres were run here;
  the `quickstart` job runs the whole path.

## Out of scope

- Refusing scans with a write-capable login (a possible `SAHIFA_REQUIRE_READ_ONLY_LOGIN` later).
- Access reports for warehouses (Snowflake, BigQuery: sprint 7).
- Keycloak in the compose bundle. Sign-in through an existing Keycloak stays as in spec 006.
- Released version tags for the quick start: S4b-4.
