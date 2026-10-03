# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may break APIs.

## [Unreleased]

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

### Fixed
- Product page: the favicon loads (the inline data URL was cut off by unescaped quotes; it now
  uses `assets/favicon.svg`), Tabayyun is linked at tabayyun-stg.siralabs.org, and the page links
  the running preview at sahifa-stg.siralabs.org.

[Unreleased]: https://github.com/Sira-Labs/Sahifa/commits/main
