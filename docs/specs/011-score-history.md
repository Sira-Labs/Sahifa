# Spec 011 — Score history per asset and store

Sprint 2, story S2-5. Depends on: spec 003 (scores with intervals), spec 004 (scans), spec 005
(store and table reports), spec 007 (assets persisted per connection), spec 010 (scan
`trigger`). Packages: `api/` (migration 0007, scores written with each scan, history routes),
`web/` (score history on the store and table reports).

Status: approved 2026-10-03 by the owner.

## Goal

Each successful scan writes its store score and every table's score, each with its interval
and dimensions, into a `scores` table. The store report and the table report show the last 30
scans as a sparkline, ending at the scan being viewed:
- the score line, with its 95 % band;
- the change since the previous scan;
- the score and interval of each point on hover or keyboard focus, with a link to that scan.

Scans finished before this spec appear in the history: migration 0007 fills `scores` from the
reports already stored.

## User story

As a data owner, I see whether my store and each table are getting better or worse across
scans, so that I can tell a real change from a one-off and see whether the fixes worked.

## Interface

### Database (migration 0007)

`scores` holds one row per scan and level, either the store or one asset:

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid PK | |
| `scan_id` | → scans, cascade | |
| `connection_id` | → connections, cascade | The store. Denormalised for the history query. |
| `asset_id` | → assets, cascade, null | null: the store score. |
| `measured_at` | timestamptz | The scan's `finished_at`. |
| `overall`, `low`, `high` | double precision, null | 0–100. Null when nothing was evaluated. |
| `checks` | int | Checks evaluated: the sum over the dimensions. |
| `dimensions` | jsonb | `{dimension: {value, low, high, checks}}`, as in the report. |

Indexes:
- unique (`scan_id`) where `asset_id` is null;
- unique (`scan_id`, `asset_id`) where `asset_id` is not null;
- (`connection_id`, `measured_at` desc) where `asset_id` is null;
- (`asset_id`, `measured_at` desc).

**Backfill.** The upgrade inserts the rows of every `succeeded` scan from its stored `report`.
Table scores join `assets` on (`connection_id`, `namespace`, `name`); a report table with no
asset row is skipped. The downgrade drops the table.

### API (behind `current_user`, read-only)

| Route | Query | Response |
|---|---|---|
| `GET /api/connections/{id}/history` | `limit` 1–100, default 30; `scan_id` optional | `{"points": [...]}`, oldest first: the last `limit` successful scans of the store, up to and including `scan_id` when it is given. 404 for an unknown connection; 404 `scan_not_in_history` when `scan_id` is not a successful scan of this connection. 422 for `limit` out of range. |
| `GET /api/assets/{id}/history` | the same | The same, for one table. 404 for an unknown asset; 404 `scan_not_in_history` when the scan has no score for this asset. |

Each point has the fields `scan_id`, `finished_at`, `trigger`, `overall`, `low`, `high`,
`checks` and `dimensions`.

### Web

- **Store report** (`/scans/$scanId`): a "Score history" panel below the store score.
  - **Sparkline.** The overall score on a 0–100 axis, with the interval as a band. The viewed
    scan is the last point and is accented. A scan with no score leaves a gap.
  - **Headline.** "Last 30 scans" (or fewer), plus the change since the previous scan, for
    example "+2.4 since 1 Oct". When the two intervals overlap, the change is marked "within
    the interval".
  - **Points.** Each point is a link to its scan's report. Hover or focus shows the date, the
    score with its interval, the checks evaluated and "scheduled" for scheduled scans.
  - **Table view.** A "Show as table" disclosure lists the same points.
  - **Fewer than 2 points.** The panel says that history starts with this scan, and draws no
    line.
- **Table report** (`/scans/$scanId/assets/$asset`): the same panel for the table, below its
  score.

## Behaviour

1. **Writing scores.** When a scan succeeds, its `scores` rows are inserted in the same
   transaction as its report, checks and findings (spec 007, spec 009):
   - one row for the store;
   - one row per table that has an asset row.

   A failed scan writes none.
2. **Reading history.** The history lists successful scans only, ordered by `measured_at`,
   then `scan_id`. `scan_id` cuts the list at that scan. Without it, the list ends at the
   newest scan.
3. **What a score means.** Scores count only active and locked checks, as before (ADR-0004).
   The history therefore shows a check-set change as a change in score. To make that visible,
   `checks` is shown with each point.
4. **Deleting.** Deleting a connection or an asset removes its history through the cascade.
5. **Security.** The routes are read-only and take UUIDs and an integer. Nothing from the data
   reaches SQL text.

## Acceptance criteria

- [ ] A successful scan writes one store row and one row per table, with the report's values.
      A failed scan writes none.
- [ ] `GET /api/connections/{id}/history` returns the last 30 successful scans, oldest first.
  - `limit` and `scan_id` cut the list as described.
  - It returns 404 for unknown ids and `scan_not_in_history`, and 422 for a bad `limit`.
- [ ] `GET /api/assets/{id}/history` does the same for a table.
- [ ] Migration 0007 fills `scores` from existing reports, upgrades and downgrades, and
      `alembic check` is clean.
- [ ] Web, store and table report:
  - the sparkline shows the points with the band;
  - the change since the previous scan, with the "within the interval" note;
  - points that link to their scans;
  - the table view;
  - the single-scan state.
- [ ] Staging: the store page of a connection with several scans shows its history. This is
      the owner's check after deploy.
- [ ] `make lint` and `make test` pass.

## Test cases

- **API, integration (`api/tests/test_history.py`, database required):**
  - scores written on success and not on failure;
  - store and table history, ordering, `limit`, `scan_id`;
  - the 404 cases and the 422;
  - a null score;
  - 401 without sign-in.
- **Migration:** the backfill from a stored report; upgrade, `alembic check`, downgrade to
  0006, upgrade again.
- **Web (`web/src/__tests__/History.test.tsx`):**
  - the sparkline renders one mark per point, and the last one is accented;
  - the change and the "within the interval" note;
  - the tooltip on focus;
  - the point links;
  - the table view;
  - the single-scan state;
  - the asset page asks for the asset's history.

## Out of scope

- Column-level history, and history per dimension in its own chart. The dimensions are stored,
  so this is a later story.
- Alerts on score drops: R2, sprint 8.
- Marking the scans where the check set changed: a later story. The checks count is shown now.
- Retention or pruning of old scores: the rows are small; revisit with the performance run
  (S3-2).
