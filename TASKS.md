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

## Sprint 1 — first scan end to end (2 Oct 2026)

- [~] **001 Repository scaffold, CI, release and deploy pipeline** — `docs/specs/001-repository-and-pipeline.md`
- [~] **002 Connectors, sampling and column profiles** — `docs/specs/002-connectors-and-profiling.md`
- [~] **003 The R1 checks, scoring with intervals, the report and the CLI** — `docs/specs/003-checks-scoring-report.md`
- [~] **004 API: connections, scans and persistence** — `docs/specs/004-api-connections-and-scans.md`
- [~] **005 Web: scans, new scan, store report, asset report, findings** — `docs/specs/005-web-scans-and-report.md`
- [ ] S1-6 product page in `Sira-Labs/siralabs.github.io` (owner: access or merge).

## Sprint 2 — checks lifecycle, worker, history

- [ ] 006 Assets, columns and checks persisted; lifecycle actions.
- [ ] 007 Procrastinate worker, `sahifa-worker` app, reaper, upload clean-up.
- [ ] 008 Findings across scans with deduplication and occurrences.
- [ ] 009 Scheduled scans; S3 sources through DuckDB with credentials by reference.
- [ ] 010 Score history per asset and store.

## Owner

- [ ] DNS `sahifa-stg.siralabs.org`; CapRover staging apps; GitHub `staging` environment
      (`deploy/caprover.md`, "Checklist for the owner").
- [ ] Push access to `Sira-Labs/siralabs.github.io` for the product page.
- [ ] Buy ISO/IEC 25024 so the catalogue can cite measure identifiers.
