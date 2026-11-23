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

- [x] **020 Invitations by link, deleting workspaces** — `docs/specs/020-invitation-links.md` (S4b-1)
      - The token never reaches a URL the server sees: link fragment, then sessionStorage, then
        request bodies; only its SHA-256 is stored. Accepting reads as the system, the token
        being the proof.
      - Token tries have their own rate-limit bucket per session, not the sign-in bucket per address.
      - `SAHIFA_ALLOWED_EMAILS` still works and logs a deprecation; the next release removes it.
- [x] **021 Install in your own environment, and what the login may do** —
      `docs/specs/021-install-and-access-check.md` (S4b-2)
      - A password gate in the web image (`SAHIFA_EDGE_AUTH=basic`) instead of Keycloak for small
        installs; off by default, so CapRover and staging do not change.
      - The access report is advice: scans still run read-only with a login that could write.
      - The CI job `quickstart` follows `deploy/quickstart.md` with a read-only and a writing login.
- [x] **022 First run: demo data, a guided first scan, empty states, error texts** —
      `docs/specs/022-first-run.md` (S4b-3)
      - `POST /api/scans/demo` writes the faulty shop (5,000 rows) as an upload of its own and
        reads it in full; no switch to turn it off, the upload clean-up removes the files.
      - The guide is the empty start page, the steps on a running scan and a note on the demo
        report, not an overlay tour: it also works for someone who comes back later.
      - Found by the matrix test: a workspace holding a scanned upload with findings could not
        be deleted (spec 020). A finding points at its scan as first and last seen, and the
        cascade from the connection failed on it. `delete_workspace` deletes findings first.
      - Found in the browser: with a failing `/api/auth/me` (a database without migrations)
        the app asked for the session thousands of times a minute. The session check now
        fails once, with a panel and a retry.
      - Advice texts live in the web (`errorAdvice` by status, `scanFailureAdvice` by reason),
        not in the API, whose messages stay as they are.
- [x] **S4b-4 stable for test users** — `docs/specs/023-stable-for-test-users.md` (17 Nov)
      - Error reporting is the API's own log, with a reference (`X-Request-ID`) the page
        shows for 500 and above; no error-tracking service, which would need an account and
        send data out of a self-hosted install (S12-3 has it).
      - The reference middleware sits inside the security headers and outside the limits, so
        413/429/507 carry it and its own 500 gets the headers. A caller's reference is kept
        only in a narrow form (8 to 64 of `A-Z a-z 0-9 . _ -`), so a proxy can set one.
      - Versioned images already existed (`release.yml`); what was missing is telling people
        which tag to take. The quick start now says: a release, or the `sha-` tag of the commit
        the footer shows, never `latest`.
      - The backup guide is tested: the CI job `quickstart` dumps, drops, restores and
        compares the scans. Restore on a new machine starts the bundle once first, because the
        role `sahifa_app` is made by the first migration and is not in a dump.
      - The feedback link is fixed to the GitHub issue chooser, not a setting.
      - Owner: tag a release for test users from `main` (for example `v0.2.0-beta.1`; `v*` tags
        are yours by CONTRIBUTING.md). It blocks nothing: until then the quick start has them
        pin `sha-<commit>`, which never moves.

## Sprint 5 — metric history, anomalies, drift

- [x] **S5-1 measure history per column** — `docs/specs/024-column-measure-history.md` (19 Nov)
      - One row per scan, table and column with the measures as one JSON object
        (`column_measures`, migration 0012), not a column or a row per measure: 30,000 rows
        for a scan of 1,000 tables, new measures without a migration, a history in one index
        range.
      - Keyed by column name, because each scan replaces the `columns` rows; a column that is
        gone keeps its history and its page.
      - Only what the profile already has is stored, with no extra query. Minimum and maximum
        of dates are text there and are left out until S5-2 decides how growing timestamps
        are baselined.
      - "Per check" of the story is not in it: failing checks already have their counts per
        scan (`finding_occurrences`); a series for passing checks comes with S5-2, which
        defines what the anomaly checks read.
      - The existing tenancy tests found that a moved connection left its measures in the old
        workspace; `move_connection` now moves them.
      - The history starts with the first scan after the update; earlier reports are not
        backfilled.

- [x] **S5-2 anomaly thresholds** — `docs/specs/025-anomaly-thresholds.md` (22 Nov)
      - Medians instead of STL (ADR-0017): histories are short and mostly irregular, and
        statsmodels would bring NumPy, SciPy, pandas and patsy into a core with four
        dependencies. The baseline is the median of the last 10 readings, or of the same
        position in the last 4 cycles.
      - The interval is conformal on the baseline's own one-step-ahead errors; a rate of 5 %
        needs 22 scans (33 with a weekly cycle). Too little history calls nothing unusual.
      - Gate G2 is `core/tests/test_anomaly.py`: 4,000 simulated histories per case. The rate
        holds for level noise (normal and skewed) and a weekly cycle read as one. A steady
        trend and an unmodelled cycle stay below 10 % at a chosen 5 %; the spec says so
        instead of promising the rate everywhere.
      - The first seasonal baseline (level plus the usual offset of the weekday) failed the
        gate: errors from before the cycle was known made the interval so wide that an
        8-sigma shift was never found. Forecasting from the same position, and measuring
        errors only after two full cycles, fixed it.
      - Only the weekly cycle of daily scans is recognised, and only on an unbroken daily
        series (each scan a day after the one before, give or take three hours): the review
        showed that a missed day shifts positions and flags an ordinary weekday. Thresholds
        are computed when asked, not stored.
      - Not in it: the check that makes a finding of an unusual reading and the chart with
        thresholds (S5-4); check 16, distribution shift, goes with drift (S5-3).

- [x] **S5-3 distribution shift (check 16)** — `docs/specs/026-distribution-shift.md` (23 Nov)
      - Against the locked baseline, not the previous scan as the catalogue said: scan by scan
        a slow drift never shows and a change is accepted without anyone deciding. The
        baseline lifecycle already holds the reference a person approved.
      - Computed on the profile, with no query: seven points of the distribution function for
        numbers (Kolmogorov–Smirnov decides, Wasserstein in interquartile ranges is the size),
        the counts per value for few values (Jensen–Shannon decides, PSI must pass its
        critical value). KS on seven points is a lower bound; a finer grid would mean more
        quantiles in the profile and the stored measures.
      - A report needs an effect of 0.1 and significance at one in a thousand. Significance
        alone would flag every large table, the effect alone every small one (ten values and
        200 rows reach a Jensen–Shannon distance of 0.1 by chance).
      - `failed` is the smallest number of rows that must have changed, so the finding weighs
        in the score like that share of failing rows.
      - The accuracy benchmark now measures every check of the catalogue (`accuracy.CHECKS`);
        the drift twin has two shifted columns in `events`.
      - No timestamps (they move with every load) and no personal data (the baseline keeps
        values).
      - CodeRabbit did not review the PR (its check ended neutral), so an independent review
        was run before the merge. It found that a value held by a quarter of the rows (zeros,
        say) was read at the highest quantile level it spans, which reported unchanged
        columns; such a share is now read within its bounds.
- [ ] **Checks 24 `sah.schema_drift` and 29 `sah.volume_trend`** (listed with S5-3 in the
      plan): both need what earlier scans saw, which a scan does not hand to the core yet
      (the API has it: `columns` per scan, `column_measures`). Next after S5-4.

## Maintenance (nightly runs)

- [x] **CI red on every PR: vulnerable API dependencies and a core test that expired**
      (14 Nov, PR #48, replaces Dependabot PR #46)
      - `pip-audit` failed on certifi, joserfc and opentelemetry-api; `main` itself last ran CI
        on 17 Oct, so it looked green. Fixed by updating, with no entry in
        `security/audit-ignore.toml`.
      - Dependabot's grouped PR only updates direct dependencies; certifi and opentelemetry-api
        are transitive (httpx, FastAPI) and were raised with `uv lock --upgrade-package`.
      - `test_rule_fires_on_faulty_shop[sah.future_dates]` failed from 12 Nov: the fixture shop
        is written for 2 Oct with a date 40 days ahead, and scans used the real clock. New
        `ScanOptions.now` (the clock when unset) is the scan's time and `started_at`; every test
        that scans the fixture shop passes the shop's time. No spec: a test fix with a small
        option, both needed in one PR because each alone leaves a required check red.
- [x] **Staging deploys raced when two PRs merged seconds apart** (14 Nov)
      - #47 and #44 merged 4 s apart; #44's run deployed first, #47's slower build deployed
        after it, so staging served the older commit and #44's run timed out in `wait-live`.
      - `deploy-staging` has a concurrency group and skips a `main` commit that is no longer
        the head (asked from the API with the job's read token); tags are not affected.
- [x] **`@eslint/js` 10** (14 Nov, replaces Dependabot PR #36): its recommended set adds
      `no-useless-assignment`, which found one unused initial value in `web/src/schedule.ts`.
- [x] **`@vitejs/plugin-react` 6** (15 Nov, replaces Dependabot PR #37): no code change; the
      Dependabot branch conflicted in the lockfile after the npm group merged, and a rebase
      cannot be requested from a run (the mention is stored altered), so the bump was redone.
- [x] **CI jobs have a time limit; a hung test names itself** (15 Nov)
      - `python api` hung in `pytest` for over 20 minutes on a web-only PR (#52) and would have
        held the PR for six hours. Every CI job now stops after 20 minutes, and pytest dumps all
        stacks after five minutes in one test (`faulthandler_timeout`), so the next hang shows
        which test it is.
      - The cause, found with a reporter that prints the stalled test and its tasks: at
        shutdown the inline runner cancelled its scans but did not wait for them
        (`ScanRunner.drain`). A cancelled scan kept its transaction open; the tests' next step,
        a synchronous delete of the test workspaces, waited for its locks while the loop that
        could end the scan stood still. It needs a scan still running when its test ends
        (`test_roles`), so it depended on timing and showed up when CI got slower or faster.
      - `drain` now waits up to 10 s for the cancelled scans; a scan inside its engine thread
        holds no session and is left behind after that. The reporter, a guard that waits for
        tasks a test left behind, and one line per test in the api job stay.
- [x] **Weekly dependency updates of 16 Nov in one PR** (replaces Dependabot PRs #55 to #60)
      - Six PRs touched three lockfiles in pairs, so each merge would have put the next into
        conflict; they were redone on one branch with `uv lock --upgrade-package` and pnpm.
      - DuckDB 2.0.0, croniter 7.0.0 and jsdom 31.0.1 are major versions that need no code
        change: every test is green on them. DuckDB is raised in `api/uv.lock` too (Dependabot
        only raised it for `core/`), so the API runs the version core is tested with.
      - Procrastinate stays at 3.10.0 here: 3.11.0 changes `procrastinate_fetch_job_v2`, which
        needs its own Alembic migration (next entry).
- [x] **Procrastinate 3.11.0** (17 Nov, the rest of Dependabot PR #59)
      - 3.11.0 changes one function, `procrastinate_fetch_job_v2`, and nothing else in its
        schema. Migration 0011 applies Procrastinate's own script, vendored as released next to
        it like 0004's schema; the downgrade reads the 3.10.0 function out of 0004's file.
      - The pin test can no longer compare 0004's file with the installed schema. It now checks
        the version, that 0011's file is the one script released after 3.10, and (with a
        database) that the migrated function is the one the installed Procrastinate ships.
      - The script is a "pre" migration: the new function serves 3.10.0 too, so the api
        migrating before the worker restarts is safe.
- [x] **Python 3.15 for the API image** (22 Nov, replaces Dependabot PR #42, open since 26 Oct)
      - It waited for wheels: the slim image has no compiler, and `httptools`, `markupsafe` and
        `pyyaml` (all from `uvicorn[standard]` and FastAPI) had none for 3.15. `httptools`
        0.9.0, `markupsafe` 3.0.4 and `pyyaml` 6.0.4 do; the lock takes them.
      - Checked before the push with a binary-only install of the locked runtime set on 3.15
        and an import of the app; the CI job `quickstart` builds the image and scans with it.
      - CI's test jobs stay on 3.12 and `requires-python` on 3.11: the image is what changes.
- [x] **Procrastinate 3.12.0, first half** (23 Nov, replaces Dependabot PR #69; #68 and #70
      merged as they were)
      - 3.12.0 ships five scripts: three "pre" (lock modes with a new defer function and type,
        a retry that fails a running job instead of raising on a queueing lock, a lock index)
        and two "post" that drop what 3.11.0 still calls. Migration 0013 applies the three
        "pre" scripts, vendored as released; the index is built `CONCURRENTLY` in an Alembic
        autocommit block, as its script demands.
      - The index is built first and the other two scripts follow in one transaction with
        the revision (the review's finding: built last, a failed build left the committed
        scripts behind and a second run failed on `CREATE TYPE`). A second run drops an
        invalid index and keeps a valid one, so migrating again always completes.
      - The "post" scripts are left for a migration one release later: the api migrates on
        start while the worker of the previous release may still defer with
        `procrastinate_defer_jobs_v1`, so dropping it in the same deploy would fail those
        scans. Until then the schema is 3.12.0's plus the old defer function, type and index.
      - The downgrade reads the 3.11.0 functions out of the files of 0004 and 0011.
- [ ] **Procrastinate 3.12.0, second half**: migration 0014 with the two "post" scripts
      (`03.12.00_50`, `03.12.00_51`; the index drop is `CONCURRENTLY` too), once staging runs
      the first half; `POST_SCRIPTS_3_12` in `api/tests/test_jobs.py` lists them.
- [ ] **Trim `column_measures`** (from spec 024): one row per column and scan, kept for ever.
      Spec 025 reads the last 120 scans of a column; the clean-up job can delete what is older.

## Owner

- [x] DNS `sahifa-stg.siralabs.org`; CapRover staging apps; GitHub `staging` environment
      (`deploy/caprover.md`, "Checklist for the owner").
- [ ] Push access to `Sira-Labs/siralabs.github.io` for the product page.
- [x] Keycloak realm `sahifa` on `miftachun.apps.data-and-ai-dude.ch`, Google and GitHub OAuth
      apps, then staging to `SAHIFA_AUTH_MODE=oidc` (`deploy/caprover.md`, section 4a).
- [ ] Buy ISO/IEC 25024 so the catalogue can cite measure identifiers.
- [ ] Apply `.github/rulesets/protect-main.json` to the live ruleset so `secrets` and
      `web image` become required (CONTRIBUTING.md); optionally turn on push protection.
      Owner: the same step (an active ruleset, plus "Allow auto-merge" in the settings) is what
      lets nightly runs enable auto-merge (ADR-0016); until then they merge by hand after CI.
