# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may break APIs.

## [Unreleased]

### Added
- **A check for changed distributions** (`sah.distribution_shift`, spec 026). Each scan
  proposes a distribution baseline for number columns and for columns with few values. Once
  you approve one, later scans report when the distribution moved: for numbers with the
  Kolmogorov–Smirnov distance and how far the values moved in interquartile ranges, for a
  mix of values with the Jensen–Shannon distance and PSI against its critical value. A report
  needs a tenth of the rows to have moved and more than a sample's noise, so neither a large
  table nor a small one is flagged for nothing. On the benchmark: 40 of 40 shifts found, no
  finding on 200 baselines with new clean data.
- **Anomaly thresholds for every measure** (spec 025, ADR-0017).
  `GET /api/assets/{id}/measures/thresholds?column=` says per measure whether the newest
  scan's value is unusual given the scans before it, and where the next one is expected, at a
  false-alarm rate you choose (5 % by default: about one ordinary reading in twenty). At 5 %
  the interval for the next scan exists after 22 scans, and the newest scan is judged from
  the 23rd on (33 and 34 for an unbroken series of daily scans, which is read with its weekly
  cycle). Not yet shown in
  the web app or raised as findings.
- **Measures over time for every column** (spec 024). Each successful scan stores what it
  measured per column: the shares of empty, distinct and blank values, mean, spread, minimum,
  maximum and quantiles, and the table's row count. A column's profile on the table page links
  to *Measures over time*: a small chart per measure over the last 30 scans and the numbers
  per scan (`GET /api/assets/{id}/measures?column=`). History starts with the first scan after
  the update (schema migration 0012).
- **A reference for every error** (spec 023). Every answer of the API carries `X-Request-ID`.
  An error Sahifa did not expect shows the reference on the page, and the API's log has one
  line `api.error` under it with the request and the stack trace. A proxy in front of Sahifa
  may set the reference itself.
- **For self-hosters** (spec 023): `docs/guides/backup-and-restore.md` (tested by CI on every
  change), `docs/guides/your-data.md` on what Sahifa reads, keeps and deletes, and in the quick
  start which image tag to install, how to update and how to go back. The footer shows the
  version with its commit, a *Feedback* link and the data note.
- **First run** (spec 022). The empty start page says what Sahifa does in three steps and
  offers *Try the demo data*: one click scans a made-up web shop with faults put in on purpose
  (`POST /api/scans/demo`), and the report says what it shows. A running scan lists its steps.
  Failed requests and failed scans say what to do next where the cause is known: the API is
  down, the role is missing, a file is too large, the database cannot be reached, the login
  was refused.
- **Explainer video on the product page**: 93 seconds on the problem Sahifa solves, how a scan
  works and what to expect, narrated, with English captions (`site/assets/video/`). Its source and
  how to re-render it are in `docs/assets/video/`.
- **Run it on your own machine** (spec 021): `deploy/quickstart.md`, a compose override for
  read-only folders and databases on the host, and an optional password gate in the web
  container (`SAHIFA_EDGE_AUTH=basic`), so a small install needs no Keycloak.
- **What the login may do** (spec 021). The connection's *Test*, every scan report and the new
  `sahifa access` command say whether the database login (or, for files, Sahifa's process) can
  only read or could write, with the tables and what to revoke. `docs/guides/read-only-login.md`
  is the one page on read-only logins.
- **Invitations by link** (spec 020). A workspace admin creates a link for an address and a role
  on `/workspaces`, copies it and sends it any way they like; the invited person opens it, signs
  in and lands in the workspace. Links work once, for that address, for 7 days
  (`SAHIFA_INVITATION_TTL_DAYS`), and can be revoked. No email is sent yet.
- **Deleting a workspace** (org admin), after typing its name: its uploads, scans, findings,
  members, invitations and audit entries go with it; the deletion stays in the default
  workspace's audit log.
- **Audit log** (spec 018). Every change a person makes is recorded with who, when, the
  workspace, and the state before and after, in the change's own transaction:
  - checks, findings and schedules;
  - scans and uploads;
  - connections, workspaces and members.

  Entries cannot be changed or deleted. Workspace admins read their workspaces' log on the new
  page `/audit` and through `GET /api/audit`; the org admin reads all of it. Earlier check and
  finding history is included.
- **Workspaces and roles** (spec 016). Connections belong to a workspace; people are viewers,
  editors or admins of workspaces. Viewers see a workspace's scans, checks, findings and
  history; editors also scan, upload and change checks, findings and schedules; admins rename
  the workspace and manage its members. The org admin (`SAHIFA_ADMIN_EMAIL`) creates
  workspaces and moves connections between them. A new page `/workspaces`, a workspace filter
  in the header, and `SAHIFA_ORG_NAME` for the name shown there.

### Fixed
- **A workspace with scanned uploads can be deleted.** Deleting it failed with a server error
  as soon as one of its scans had findings.
- **A failing API is no longer flooded by the web app.** When the session check failed, every
  part of the page asked again, thousands of times a minute. The page now says that the API
  is down, with a retry.
- **Shutting down the API no longer leaves a scan holding database locks.** In inline mode a
  running scan was cancelled but not waited for, so its transaction could outlive the
  shutdown. The API now waits up to ten seconds for cancelled scans to stop.
- **Staging always ends on the newest commit.** Two merges a few seconds apart raced: the older
  commit was deployed last and the newer release run waited ten minutes for a version that
  never went live. Deploys to staging now run one at a time, and a run whose commit is no
  longer the head of `main` leaves the deploy to the newer run.
- **The core's tests no longer depend on the day they run.** The test shop is written for a
  fixed day with one date 40 days ahead; scans ran on the real clock, so from 12 November the
  "dates in the future" test found nothing. `ScanOptions.now` sets the time a scan measures
  against, and the tests pin it.
- The compose bundle's web container started only with `SAHIFA_DOMAIN` set; without a domain
  Caddy got an empty site address and exited. Found by the new quick-start CI job.
- Two admins inviting the same address at once no longer make one of them fail, and cleanup
  after deleting a workspace no longer fails when a file vanishes while it is measured.

### Deprecated
- `SAHIFA_ALLOWED_EMAILS`: invitation links replace it. It still works in this release and logs a
  warning at start; the next release removes it.

### Changed
- The API image runs on Python 3.15 (was 3.14).
- Dependencies: DuckDB 2.0, croniter 7 and jsdom 31, with the weekly minor updates of core,
  API and web.
- Procrastinate 3.12.0, with schema migration 0013 (its three "pre" scripts): a retry that
  meets a queueing lock now fails the job instead of leaving it running for ever, and the
  worker finds the jobs sharing a lock through an index. The migration builds that index
  without blocking writes; should it be interrupted, start the API again and it completes. Also the weekly minor updates (FastAPI 0.165, DuckDB 2.0.1,
  sqlglot 30.33, TanStack Query 5.108, ESLint 10.15).
- Procrastinate 3.11.0, with schema migration 0011: the worker picks its next job without
  scanning every queued job. The API migrates on start, as for every release.
- **Access comes from memberships.** A signed-in person needs a workspace (or to be the org
  admin). Until invitations arrive, an address in `SAHIFA_ALLOWED_EMAILS` becomes an editor of
  the `Default` workspace; everything that existed before moves to `Default`.
- Creating a connection needs the admin role in its workspace; uploads and new connections name
  their workspace when the person works in several.
- Every role check goes through one access object (spec 017).

### Security
- **Row-level security in Postgres** on every workspace-owned table, failing closed, so a query
  that forgets its filter still sees nothing of another workspace. The API switches to the
  role `sahifa_app` in each transaction, and refuses to start in prod when its database login
  would bypass row-level security.
- **A role matrix test** (spec 017) asks all 32 workspace routes as 7 kinds of caller and compares
  each answer with the role table. It fails when a route loses its role check or its workspace
  scope, and when a new route has no line in the matrix.
- **Secret scanning in CI** (spec 019). gitleaks scans the whole history on every pull request.
  A self-test shows that a committed token fails the build.
- **The web container no longer runs as root.** Caddy runs as uid 10001 and still serves on
  ports 80 and 443. In the compose bundle, a one-shot `web-volume` service hands an existing
  certificate volume to that user, so upgrading needs no manual step.
- **Vulnerable API dependencies updated.** certifi 2026.10.23 drops a root whose intermediates
  were compromised (GHSA-6q48-6c7w-9gw2); joserfc 1.8.0 checks token size before splitting
  (GHSA-9pg5-8c7x-5hfx); opentelemetry-api 1.45.2 fixes two slow regular expressions on trace
  headers (GHSA-xcq7-p3pf-p88h, GHSA-mf5v-w3w3-f6cg). The API's other minor updates of
  9 November (FastAPI 0.162, pydantic 2.14 and others) come with it.

## [0.1.0] - 2026-10-09

The first preview (R1). It scans uploaded CSV, Parquet and JSON files and Postgres databases.
It runs 20 checks, scores six quality dimensions with 95 % intervals, and explains each
finding. Staging: <https://sahifa-stg.siralabs.org>.

### Known limitations
- **No production release yet.** The promote dry run to production (S3-3) is deferred to the
  first production deploy, by the owner's decision of 7 Oct 2026. 0.1 runs on staging only.
- **Locked `range` baselines raise false alarms.** A `range` baseline locked on one scan raises
  a finding on legitimate new data most of the time (122 of 200 cases in the accuracy
  benchmark); timestamps that keep growing always do. Lock `range` only on columns with fixed
  limits. Baselines learnt from several scans come in 0.2.
- **Sampled scans miss rare faults.** A sampled scan can miss faults in only a few rows, and
  rarely sees duplicates. The 95 % intervals cover the true share in 85–100 % of benchmark
  cases. Use `--all-rows` (CLI) or a full read when every row matters.
- **Sources:** Postgres and files only. Snowflake, BigQuery, SAP HANA, S3 and Iceberg come in
  0.2.
- **Scores:** history is per scan; anomaly thresholds, drift and explanations of where
  failures cluster come in 0.2.

### Added
- R0 research and design: research 01–04 (DataKitchen TestGen as reference, the data-quality
  landscape, methods, synthesis and positioning), product vision, domain model, system
  architecture, ADRs 0001–0013, check specification and the catalogue of the first 30 checks,
  roadmap, first specs, the CapRover deployment plan and the product page.
- First scan pipeline: the `sahifa_core` library profiles every table or file of a source,
  generates checks from the profile, evaluates them in the source (SQL pushdown on Postgres,
  DuckDB on CSV, Parquet and JSON files), scores each quality dimension with a 95 % interval
  and reports findings with evidence; the `sahifa` CLI (`sahifa synth`, `sahifa scan`) runs
  it from a terminal.
- CI for core, api and web; release pipeline publishing `sahifa-api` and `sahifa-web` images
  to GHCR with SBOM, provenance and a Trivy scan, deploying staging and promoting the same
  digests to production (ADR-0012); compose bundles and the CapRover guide in `deploy/`.
- Apache-2.0 licence (ADR-0008), contribution guide, security policy, code of conduct, issue
  and pull request templates, Dependabot, CODEOWNERS and the `main` and release-tag rulesets.
- Sign-in through a Keycloak realm with Google, GitHub and passkeys (spec 006): the API is the
  backend-for-frontend with an HttpOnly session cookie, CSRF header, devices, logout and
  back-channel logout; only the admin and allowed emails get access. Installs behind HTTP
  basic auth keep working in `proxy` mode.
- Checks persist per asset (spec 007): each scan stores the connection's assets, columns and
  checks; the next scan keeps locked checks' parameters, never re-creates retired ones and
  refreshes open baselines from the new profile. The asset report lists checks by status with
  approve, reject, lock, unlock, retire and restore, and every change is recorded with who made
  it (`/api/assets`, `/api/checks`, migration 0003).
- Scans can run in a separate worker (spec 008): with `SAHIFA_SCAN_EXECUTION=queue` the API
  enqueues each scan in a Procrastinate queue on its own Postgres and `sahifa-worker` (the API
  image with `SAHIFA_ROLE=worker`) runs it. A reaper fails scans whose worker stopped and
  re-queues scans left without a job; old upload folders are deleted hourly after
  `SAHIFA_UPLOAD_TTL_DAYS` (also in the default inline mode). `/healthz` lists connected
  workers by commit. Migration 0004; the compose bundle gains a `worker` service, CapRover a
  worker app and a one-click template for it.
- Findings across scans (spec 009): each failing check has one finding that is not resolved,
  and every scan that finds the problem again adds an occurrence. A check that passes again
  resolves its finding; failing later reopens the same one. Signed-in users acknowledge,
  resolve, mute (optionally until a date) and reopen findings with a note, and every change is
  recorded. New `/findings` page and `/api/findings`; the scan findings page shows each
  finding's status. Migration 0005 renames the per-scan `findings` table to
  `finding_occurrences`.
- Scheduled scans (spec 010): a connection gets a schedule, a preset ("Nightly at 02:00",
  "Every 6 hours", "Weekly on Monday at 06:00") or a 5-field cron in an IANA time zone,
  daylight saving included. The worker (or, inline, the API) starts due scans every minute,
  never while the connection's previous scan is queued or running, and runs a missed slot
  once after an outage. Scheduled scans are marked "scheduled" in the scans list.
  `/api/connections/{id}/schedule`, `scans.trigger`, `SAHIFA_SCHEDULE_MIN_INTERVAL_MINUTES`
  (default 60), migration 0006.
- Score history (spec 011): every successful scan stores its store score and each table's, with
  the interval and dimensions. The store and table reports show the last 30 scans as a line
  with its 95 % band, the change since the previous scan (marked when within the interval),
  each point linked to its scan, and a table view. `/api/connections/{id}/history`,
  `/api/assets/{id}/history`, migration 0007, which fills the history from stored reports.
- Security baseline (spec 012): HSTS, CORP, framing and cache headers at the edge and
  no-store, nosniff and a none-CSP on the API; request bodies limited while they stream (1 MB,
  uploads `SAHIFA_MAX_UPLOAD_TOTAL_MB`), uploads checked for matching content and cleaned
  names, refused when the disk runs low; rate limits per session or address with 429 and
  `Retry-After`; `/api/docs` off in prod; CI fails on known vulnerabilities and on licences
  outside ADR-0008 (psycopg allowed by ADR-0015). The checklist is `docs/security/baseline.md`.
- Performance (spec 013): a 1,000-table Postgres schema (64 million rows, 100k-row samples)
  scans in 8 min 13 s on 2 vCPU. Scans use two read-only Postgres sessions at once
  (`SAHIFA_SCAN_WORKERS`, CLI `--workers`); each asset reports its seconds and queries; examples
  are fetched for at most 10 failing checks per table (findings first). `sahifa bench-schema`
  creates the benchmark schema; the numbers are in `docs/architecture/performance.md`.
- Accuracy benchmark (spec 014): `sahifa bench-accuracy` measures each R1 check against the
  faults known to be in the synthetic shop, over 20 seeds. It reports detection, exact counts,
  unexpected flags, false alarms on the clean twin and of locked baselines on new data, and
  detection and interval coverage in sampled scans. The table is in `docs/checks/catalogue.md`:
  every check finds every fault on a full read, and the clean twin stays silent.
  `sahifa synth --drift` writes the clean twin with one fault per baseline check.

### Changed
- The API image runs on Python 3.14 (was 3.12); the API and core tests pass on 3.14.8.
- Web tooling: Vite 8, Vitest 5 and ESLint 10; the GitHub Pages actions are on their current
  major versions.

### Fixed
- The foreign-key check no longer runs once per sampled row against a text cast of the parent:
  it counts orphans with an anti-join of its own. A table with a foreign key to a large
  parent could keep a scan from finishing.
- Reports no longer call a sampled score a "full read": scores are rounded to one decimal, so
  a narrow sampled interval can show equal bounds. "Full read" and "every row read" now appear
  only for a table read in full, or a store with no sampled table; otherwise the interval is
  shown (`99.0–99.0`).
- Product page: the favicon loads (the inline data URL was cut off by unescaped quotes; it now
  uses `assets/favicon.svg`), Tabayyun is linked at tabayyun-stg.siralabs.org, and the page links
  the running preview at sahifa-stg.siralabs.org.

[Unreleased]: https://github.com/Sira-Labs/Sahifa/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Sira-Labs/Sahifa/commits/v0.1.0
