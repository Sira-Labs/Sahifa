# Sahifa — Backlog

Status legend: `[ ]` open, `[~]` in progress, `[x]` done. One spec per session; mark it here
and add one line per non-obvious decision below the entry (these are the session notes the
next session reads). Sprint priorities, actual dates and the forecast live in
`docs/roadmap/sprints.md`; the story ids there (`S1-2`) map to specs here.

## R0 — research and design (done 1–2 Oct 2026)

- [x] Research 01–04 (DataKitchen reference, landscape, methods, synthesis), name and
      repository chosen by the owner.
- [x] Vision, domain model and scoring, system architecture, frontend design, ADRs 0001–0013,
      check specification and catalogue, roadmap, sprint plan, specs 001–005, CapRover plan,
      product page design (`site/index.html`).

## Sprint 1 — first scan end to end (done 2 Oct 2026, PR #1)

- [x] **001 Repository scaffold, CI, release and deploy pipeline** — `docs/specs/001-repository-and-pipeline.md`
      - Images published to GHCR on 2 Oct (release run 2); `deploy-staging` skips until the owner
        sets `CAPROVER_SERVER` on the `staging` environment. Compose bundle not yet run end to end.
      - CapRover one-click template added (`deploy/caprover/one-click/sahifa.yml`); it names apps
        `<name>-db/-api/-web`, so staging from the template is `sahifa-stg-api`, not `sahifa-api-stg`.
- [x] **002 Connectors, sampling and column profiles** — `docs/specs/002-connectors-and-profiling.md`
      - Postgres samples are CTEs (`TABLESAMPLE BERNOULLI … REPEATABLE`): a read-only session cannot
        create temp tables. Views are sampled as their first rows, and the report says so.
      - Literals go through SQLGlot with NUL rejected; `standard_conforming_strings=on` is forced.
- [x] **003 The R1 checks, scoring with intervals, the report and the CLI** — `docs/specs/003-checks-scoring-report.md`
      - Baseline checks (pattern, accepted values, length, range, freshness) only propose on a first
        scan, so "every R1 check fires on the faulty shop" holds for the 15 rule checks; baselines
        are tested as proposed and unscored. Spec criterion to be reworded in the next spec PR.
      - Asset dimension = weighted mean of column scores × product of asset-level checks.
      - `sah.outliers` tolerance 1 %: the demo shop injects 2 % decimal-shift outliers.
- [x] **004 API: connections, scans and persistence** — `docs/specs/004-api-connections-and-scans.md`
      - Scans run in a thread (ADR-0009) until spec 008; findings rows carry evidence as jsonb.
      - `Scan` also returns `connection_kind` and `files` (the web app uses both).
- [x] **005 Web: scans, new scan, store report, asset report, findings** — `docs/specs/005-web-scans-and-report.md`
      - Built and tested (34 tests, layout checked at 390 and 1280 px); the live round trip waits
        for staging.
- [ ] S1-6 product page in `Sira-Labs/siralabs.github.io` (owner: access or merge).

## Sprint 2 — sign-in, checks lifecycle, worker, history

- [x] **006 Sign-in through Keycloak (BFF)** — `docs/specs/006-sign-in-keycloak-bff.md` (PRs #2, #3)
      - Ported from Tabayyun spec 013 (`sahifa.auth`); staging runs `oidc` since 2026-10-02 and the
        owner signed in with Google, GitHub and a passkey.
      - Access is `SAHIFA_ADMIN_EMAIL` plus `SAHIFA_ALLOWED_EMAILS`, computed per request, not stored.
      - Third auth mode `proxy`: in prod an unset mode resolves to `proxy` when
        `SAHIFA_ACCESS_GATE=basic-auth-at-proxy` is set, so today's staging keeps starting.
      - No SECURITY DEFINER login function and no identities table: one DB login, no RLS yet;
        `users` holds (issuer, subject); a known identity with another user's email gets 409.
      - Route ids under the new layout route are `/_app/...` (`getRouteApi` in four pages).
      - "Add a passkey" runs Keycloak's passkey registration (`kc_action`) after a fresh sign-in;
        the account console alone could not add a first passkey (spec 006, decision 7).
- [x] **007 Assets, columns and checks persisted; lifecycle actions** — `docs/specs/007-checks-persisted-lifecycle.md`
      - `ScanReport.checks` holds the reconciled specs before evaluation (evaluated copies): the
        freshness check writes its measured age into its params and would otherwise regenerate
        every scan. `report_version` is 2; version 1 reports still load and render.
      - Unevaluated reasons beyond `column_missing`: `parent_missing` (a saved foreign key whose
        parent table is gone) and `unknown_type`, so a stale saved check never fails the asset.
      - An inferred foreign key dropped for weak evidence is not persisted; a locked or manual one
        is always evaluated.
      - A scan regenerates `params`, `columns`, `severity` and `max_fail_ratio` of open generated
        checks; the event records the params. Unchanged checks only get `last_scan_id`, no version.
      - The persist step skips a check whose version differs from the one loaded at scan start,
        and the UPDATE repeats the guard (`WHERE version = loaded`); concurrent inserts use
        `ON CONFLICT DO NOTHING`. Assets that failed keep their old columns and row count.
      - `check_events.at` defaults to `clock_timestamp()` so events of one transaction order;
        `actor` is the email, `scanner`, `dev` or `proxy`; deleting a user keeps it.
      - 409 bodies carry `detail` (`stale_version`, `invalid_transition`), `version` or `status`
        and a `message` the web shows; the auth test fixture deletes users instead of truncating.
- [x] **008 Procrastinate worker, `sahifa-worker` app, reaper, upload clean-up** — `docs/specs/008-worker-reaper-cleanup.md`
      - `SAHIFA_SCAN_EXECUTION=inline` stays the default; CapRover switches to `queue` once the
        owner creates the worker app (checklist item 8). The compose bundle runs `queue` with a
        `worker` service.
      - Commit-then-defer, not a transactional enqueue (ADR-0009 update): Procrastinate has its
        own psycopg pool; a failed defer fails the scan, the reaper re-queues the rest.
      - Procrastinate pinned to 3.10.0; migration 0004 applies its `schema.sql` vendored next to
        it (MIT notice kept), so 0004 never changes; a test fails on a version bump.
      - The clean-up uses the existing `SAHIFA_UPLOAD_TTL_DAYS` (no `..._RETENTION_HOURS`, owner);
        folders map to scans through the connection name `upload-<folder>`.
      - Worker and reaper share one threshold (`SAHIFA_REAPER_STALE_MINUTES`, also Procrastinate's
        `stalled_worker_timeout`); a cancelled job marks its scan interrupted immediately.
      - `execute_scan` claims a scan with `SELECT ... FOR UPDATE` and runs only `queued` scans,
        for both modes, which makes the job idempotent.
      - The worker has its own one-click template (`sahifa-worker.yml`), since a CapRover template
        cannot make an app optional; the worker healthcheck looks for its process in `/proc`.
- [x] **009 Findings across scans: deduplication, occurrences, status** — `docs/specs/009-findings-across-scans.md`
      - Migration 0005 renames `findings` to `finding_occurrences` (indexes and constraints too);
        old occurrences keep `finding_id` null. Model `FindingOccurrence`, new `Finding`, `FindingEvent`.
      - "Evaluated and passed" comes from the report (a result on an asset without error, scoring,
        not a finding); retired, unevaluated and dropped checks have no result. No core change.
      - Linking reuses `persist_checks`' asset ids (new `Persisted.asset_ids`); a check retired
        during the scan keeps its finding and gets an unlinked occurrence (the person wins).
      - Concurrency: insert `ON CONFLICT DO NOTHING` on the partial unique index, reopen in a
        savepoint; either conflict retries as "recur". Every scanner change bumps `version`.
      - `muted_until` is cleared whenever a finding leaves `muted`; extra index on `check_id` for
        the reopen lookup; a blank note is stored as null.
      - Web: `/findings` with a single status select ("Needs attention" default), cards updated in
        place, "Show history" panel and `/findings/$id`; mute end is a date (end of that local day).
- [x] **010 Scheduled scans per connection** — `docs/specs/010-scheduled-scans.md` (S3 sources follow in R2, sprint 7)
      - Pending: the owner's staging check (a nightly schedule produces a scan the next morning).
      - DST follows the wall clock: croniter walks naive local times, zoneinfo maps them with
        fold=0 (a repeated time fires once, a skipped one after the jump); stored in UTC.
      - Minimum interval = smallest gap of the next 50 UTC fire times (nightly is 23 h in March).
      - `jobs.start_scan` is the one hand-off (runner or defer) for manual, uploaded and scheduled
        scans; `run_due_schedules` lives in `jobs.py` beside `reap` and takes `now` and the runner.
      - Due run: lock (`SKIP LOCKED`, 20), insert scans, move `next_run_at` past now, commit, then
        start; a failed defer sets `failed_to_queue` afterwards. Runs do not bump `version`.
      - Inline mode runs the due job at the start of every minute in the API (`main.py`).
      - `PUT` without `version` on an existing schedule (or with one when none exists) is 409.
      - croniter is typed `Any` (mypy override, no stubs); `tzdata` added so zoneinfo never
        depends on the image's `/usr/share/zoneinfo`.
      - Web: schedule in an expandable row per connection, a Schedule column, "scheduled" tag in
        the scans list; sample rows are not editable in the web (null keeps the setting).
- [x] **011 Score history per asset and store** — `docs/specs/011-score-history.md`
      - Pending: the owner's staging check (the store page of a connection with several scans).
      - One `scores` row per scan and level (store, or one asset) with the dimensions as JSON,
        not one per dimension (owner, 2026-10-03; domain model updated); no column level.
      - Written in `_succeed`'s transaction; `connection_id` and `measured_at` copied from the
        scan so a history is one index range; order (`measured_at`, `scan_id`), cut by `scan_id`.
      - Migration 0007 backfills from `scans.report` in SQL; report tables without an asset
        row are skipped.
      - Web: y-axis fitted to the scores shown (≥ 4 points, within 0–100) instead of 0–100,
        where scores at 98–99 were a flat line; points are HTML links over the SVG.

## Sprint 3 — hardening, staging, release 0.1

- [x] **012 Security baseline** — `docs/specs/012-security-baseline.md`, checklist in
      `docs/security/baseline.md`
      - The licence job found psycopg (LGPL-3.0): allowed by ADR-0015 (owner, 2026-10-03).
      - Rate limits key on the hashed session cookie, not the user id: they run before FastAPI
        reads an upload, where the user is unknown without a database lookup.
      - The size middleware replaces FastAPI's 400 for a cut-off body with its own 413.
      - uvicorn and Caddy trust `X-Forwarded-For` from private ranges only; before, the api saw
        CapRover's nginx as every client.
      - Follow-ups in the baseline: secret scanning and Caddy as non-root (sprint 4), limits
        shared across replicas (R3), signature check at deploy (R2).
      - Owner: raise `client_max_body_size` on `sahifa-web` to the upload limit (deploy/caprover.md).
- [x] **013 Performance run on a 1,000-table schema** — `docs/specs/013-performance-run.md`,
      numbers in `docs/architecture/performance.md`
      - 8 min 13 s with two workers (15 min 47 s with one), Postgres and scan pinned to 2 CPUs;
        before: did not finish (about 3 days extrapolated).
      - The cause was the foreign-key check: a text-cast NOT EXISTS inside the batched
        aggregate, O(sample x parent); now its own anti-join query, native comparison when
        the logical types match.
      - Workers on Postgres only (DuckDB samples are temp tables of one connection).
      - Regex guards dropped (3 %, and `\s` equivalence not certain); examples cap 10, not 5,
        since the demo shop has six findings on two tables.
      - Reports equal across worker counts apart from scan-time-relative values (freshness
        age, future dates).
- [ ] S3-3 Staging live, promote dry run to production. Staging is live; the dry run is deferred
      to the first production deploy (owner, 7 Oct), together with the owner's staging check.
- [x] **014 Accuracy benchmark** — `docs/specs/014-accuracy-benchmark.md`, table in
      `docs/checks/catalogue.md` ("Accuracy benchmark")
      - Fault list counted from the final rows, not from the injections: duplicated order keys
        leave invoices with an order id that no longer exists, and that counts.
      - Matching is by count per check, asset and column; checks report counts, not row ids.
      - `--rows` at least 2,500, so that products (rows / 50) reach the 50 rows baselines need.
      - The sampled scan uses each seed as its sample seed: the shop's faults sit at fixed
        rows, and one sample seed always saw or always missed the same ones (0 % against
        100 % for two neighbouring rows).
      - Baselines are locked, not just activated: an active generated check takes the new
        scan's parameters (spec 007), so it can never see drift.
      - Follow-up, sprint 5 (S5-1, S5-2): a locked `range` baseline fires on legitimate new
        data in 122 of 200 cases (continuous columns and timestamps); baselines from several
        scans, with a tolerance, and no upper bound on timestamps that grow.
      - Follow-up: interval coverage 85 % for `not_blank` (17 of 20 groups, 5 placeholders in
        1,000 rows, half of them sampled). Compare the Wilson interval with the
        finite-population correction against an exact hypergeometric interval for rare faults.
- [x] **015 Release 0.1** — `docs/specs/015-release-0-1.md`, tag `v0.1.0` (pre-release, 9 Oct)
      - The tag is on efd6f33, which includes the Dependabot updates of PR #26; kept, not moved,
        and the changelog lists those updates under 0.1.0.
      - Tagged with G1 partly open, by the owner's decision of 7 Oct: the promote dry run and
        the owner's staging check come with the first production deploy. The roadmap records
        what was met.
      - One version for core and api: a test asserts `/api/version` equals both
        `__version__`s, since the api ships the engine.
      - The owner published a GitHub pre-release with notes taken from the changelog.

## Sprint 4 — workspaces, roles, audit

- [x] **016 Workspaces, memberships and roles with row-level security** —
      `docs/specs/016-workspaces-and-roles.md` (S4-1, with member management from S4-3)
      - A superuser login bypasses row-level security even with `FORCE`; migration 0008 creates
        `sahifa_app` and every API transaction switches to it. Prod refuses to start (exit 4)
        when the login would bypass row-level security and cannot switch.
      - The scope is set per transaction from the session (`set_config(…, true)` at each
        begin), so mid-request commits keep it and pooled connections never leak it.
      - The org admin also names a workspace for new connections and uploads once there are
        several: nothing lands in the broad `Default` by accident.
      - An allowed email removed from every workspace comes back as an editor of `Default`
        until it leaves `SAHIFA_ALLOWED_EMAILS` (S4-3 retires the setting).
      - Tests that create workspaces delete them afterwards; the older tests assume one.
- [x] **017 Role matrix: every route against every role** — `docs/specs/017-role-matrix.md` (S4-2)
      - 32 workspace operations × 7 callers agree with spec 016's table; three meta-tests show the
        matrix fails without the role check, the workspace scope or the sign-in.
      - Every role check is now an `Access` method, so there is one way for a route to check a
        role and one place to switch them off in the meta-test.
      - A new route fails `test_every_route_is_classified` until it has a line in the matrix.
- [x] **018 Audit log of changes** — `docs/specs/018-audit-log.md` (S4-4)
      - One append-only table, written in each change's transaction; a trigger refuses UPDATE and
        DELETE for every role except a deleted user's SET NULL and a marked purge (S4-3).
      - People's changes only; the scanner's stay in each object's history. The existing check and
        finding history from people is backfilled.
      - Creating a workspace widens the request's scope and flushes the workspace before its entry.
- [x] **019 Security follow-ups** — `docs/specs/019-security-followups.md` (S4-5)
      - gitleaks binary with a pinned checksum rather than the action (which needs a licence key
        for organisation repositories); a self-test with a generated token proves the gate.
      - Caddy as uid 10001 with the bind capability; a one-shot `web-volume` service in compose
        re-owns old certificate volumes. CapRover's web app has no volume, so nothing changes there.
- [ ] S4-3 invitations by email: moved to S4b-1 as invitation links (no SMTP yet).

## Sprint 4b — ready for test users (inserted by the owner, 10 Oct)

Production is postponed. Test users install Sahifa in their own environment, with their own
databases and files, and get in by invitation link; staging serves demos.

- [ ] **020 Invitations by link, deleting workspaces** — `docs/specs/020-invitation-links.md` (S4b-1)
- [ ] S4b-2 install in your own environment; the connection check shows what the login may read
      and warns when it may write.
- [ ] S4b-3 first run: demo data, guided first scan, empty states, error texts.
- [ ] S4b-4 stable for test users: versioned images, error reporting, backup guide, data note,
      feedback link.

## Owner

- [x] DNS `sahifa-stg.siralabs.org`; CapRover staging apps; GitHub `staging` environment
      (`deploy/caprover.md`, "Checklist for the owner").
- [ ] Push access to `Sira-Labs/siralabs.github.io` for the product page.
- [x] Keycloak realm `sahifa` on `miftachun.apps.data-and-ai-dude.ch`, Google and GitHub OAuth
      apps, then staging to `SAHIFA_AUTH_MODE=oidc` (`deploy/caprover.md`, section 4a).
- [ ] Buy ISO/IEC 25024 so the catalogue can cite measure identifiers.
- [ ] Apply `.github/rulesets/protect-main.json` to the live ruleset so `secrets` and
      `web image` become required (CONTRIBUTING.md); optionally turn on push protection.
