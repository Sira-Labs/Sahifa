# Spec 005 — Web: scans, new scan, store report, asset report, findings

Sprint 1, story S1-5. Depends on: spec 004; `docs/frontend/01-frontend-design.md`.
Packages: `web/`.

## Goal

In the browser a person lists scans, starts one from uploaded files or a connection, watches
it run, and reads the store report, an asset's columns and checks, and the findings, in the
light and dark themes, on a phone and a desktop.

## User story

As a data owner, I open Sahifa, drop three exports on the page and read what is wrong with
them without reading JSON.

## Interface

Routes: `/` (scans), `/scans/new`, `/scans/$scanId` (store report),
`/scans/$scanId/assets/$asset` (asset report), `/scans/$scanId/findings` (findings with
`?severity=&dimension=&asset=` search params), `/connections`.

Components: `ScoreCard` (value, interval, dimension bars), `IntervalBar`, `SeverityChip`,
`StatusChip`, `FindingCard`, `ColumnRow`, `UploadDropzone`, `SqlBlock` (copy button).

API client `api.ts` with typed functions for every route in spec 004; `useScanPolling`
polls `GET /api/scans/{id}` every 2 s while `queued` or `running`.

## Behaviour

1. `/` lists scans newest first with "Load more" by cursor; empty state invites a first scan.
2. `/scans/new` validates extension, size and count before upload, shows per-file errors, and
   posts; on `202` it navigates to the report.
3. The report shows progress while the scan runs, the error if it failed, and the report
   when it succeeded; a refresh shows the same.
4. Every number uses tabular figures; intervals read "92.7 · 92.3–93.1"; a zero-width interval
   reads "92.7 · full read".
5. API errors show the API's message and a retry action.

## Acceptance criteria

- [ ] `pnpm lint`, `pnpm build` and `pnpm test` pass.
- [ ] Upload → report round trip works against `make api-dev` with the faulty shop.
- [ ] No horizontal scroll at 390 px on any route; both themes legible.

## Test cases

vitest + Testing Library: `ScansList.test.tsx` (rows, empty state, load more),
`NewScan.test.tsx` (client-side validation, submit), `Report.test.tsx` (score card, intervals,
findings summary, running state, failed state), `Findings.test.tsx` (filters), `api.test.ts`
(error mapping), `useScanPolling.test.tsx` (stops when finished).

## Out of scope

Check lifecycle actions (006), score history charts (010), sign-in (sprint 4).
