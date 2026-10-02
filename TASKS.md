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
- [ ] 009 Findings across scans with deduplication and occurrences.
- [ ] 010 Scheduled scans per connection (S3 sources follow in R2, sprint 7).
- [ ] 011 Score history per asset and store.

## Owner

- [x] DNS `sahifa-stg.siralabs.org`; CapRover staging apps; GitHub `staging` environment
      (`deploy/caprover.md`, "Checklist for the owner").
- [ ] Push access to `Sira-Labs/siralabs.github.io` for the product page.
- [x] Keycloak realm `sahifa` on `miftachun.apps.data-and-ai-dude.ch`, Google and GitHub OAuth
      apps, then staging to `SAHIFA_AUTH_MODE=oidc` (`deploy/caprover.md`, section 4a).
- [ ] Buy ISO/IEC 25024 so the catalogue can cite measure identifiers.
