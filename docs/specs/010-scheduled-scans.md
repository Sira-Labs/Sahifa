# Spec 010 — Scheduled scans per connection

Sprint 2, story S2-4. Depends on: spec 004 (connections, scans), spec 006 (sign-in, CSRF,
actor), spec 008 (Procrastinate app, worker, inline background tasks). Packages: `api/`
(migration 0006, schedules, a due-schedule job, routes), `web/` (schedule on the connections
page, scheduled scans marked in the list).

Status: approved 2026-10-03 by the owner.

## Goal

A signed-in user gives a connection a schedule, either a cron expression with a time zone or a
preset such as "nightly at 02:00". Sahifa then scans that connection on time without anyone
pressing a button. Scheduled scans look exactly like manual ones, marked "scheduled" in the
scans list. A schedule never starts a second scan while the connection's previous scan is still
queued or running. After an outage, a missed run happens once, not once per missed slot.

## User story

As a data owner, I let Sahifa scan my database every night, so that each morning the report and
the findings reflect yesterday's data without my doing anything.

## Interface

### Database (migration 0006)

| Table | Columns |
|---|---|
| `scan_schedules` | `id` uuid PK, `connection_id` → connections (cascade), unique: one schedule per connection. `cron` text (5 fields), `timezone` text (IANA name, default `UTC`), `enabled` bool, `sample_rows` int null (null: the setting's default), `next_run_at` timestamptz null (null when disabled), `last_run_at` null, `last_scan_id` → scans (set null), `last_outcome` text null (`queued`, `skipped_running`, `failed_to_queue`, `invalid_schedule`), `version` int, `created_at`, `updated_at`, `updated_by` text (actor). Index (`enabled`, `next_run_at`). |
| `scans` | New column `trigger` text not null, default `manual`, CHECK (`manual`, `schedule`). |

### Settings

| Name | Default | Meaning |
|---|---|---|
| `SAHIFA_SCHEDULE_MIN_INTERVAL_MINUTES` | `60` | A cron that fires more often than this is refused with 422. It protects sources and the worker. |

### Due-schedule job

- **Queue mode:** a Procrastinate periodic task, `run_due_schedules`, runs every minute on the
  `maintenance` queue with a queueing lock.
- **Inline mode:** the API runs the same function every minute in a background task, as the
  upload clean-up does (spec 008).

Each run does the following:

1. Select enabled schedules with `next_run_at <= now()`, using `FOR UPDATE SKIP LOCKED`, at
   most 20 per run.
2. For each one:
   1. If the connection has a scan that is `queued` or `running`, set `last_outcome =
      skipped_running`.
   2. Otherwise, create a scan (`trigger = schedule`, `sample_rows` from the schedule or the
      setting). Queue it exactly as `POST /api/scans` does (inline or queue mode) and set
      `last_scan_id`, `last_outcome = queued`.
      - If queueing fails, set `last_outcome = failed_to_queue` and leave the scan failed with
        its error, as spec 008 does.
   3. Set `last_run_at = now()` and `next_run_at` to the next cron time **after now**, in the
      schedule's time zone and stored in UTC. A worker that was down for three nights therefore
      runs once, not three times.

### API (behind `current_user`; changes need the CSRF header)

| Route | Request | Response |
|---|---|---|
| `GET /api/connections/{id}/schedule` | — | `{"cron", "timezone", "enabled", "sample_rows", "next_run_at", "next_runs": [3 next times, ISO, UTC], "last_run_at", "last_scan_id", "last_outcome", "version", "updated_at", "updated_by"}`. 404 `no_schedule` when there is none; 404 for an unknown connection. |
| `PUT /api/connections/{id}/schedule` | `{"cron": "0 2 * * *", "timezone": "Europe/Zurich", "enabled": true, "sample_rows": null, "version": n?}`. `version` is required when a schedule exists. | 200 with the schedule above (created or replaced). 422 for an invalid cron, an unknown time zone, an interval below the minimum, or an upload connection. 409 `stale_version`. |
| `DELETE /api/connections/{id}/schedule` | — | 204. 404 when there is none. |
| `GET /api/connections` | unchanged | Each item gains `schedule`: `{"cron", "timezone", "enabled", "next_run_at"}` or null. |
| `GET /api/scans`, `GET /api/scans/{id}` | unchanged | Each scan gains `trigger`. |

**Validation:**
- **Cron:** exactly 5 fields, parsed with `croniter` (MIT). It is a direct dependency now, no
  longer only Procrastinate's.
- **Time zone:** must be a known `zoneinfo` name.
- **Minimum interval:** the smallest gap between the next 50 cron times, computed in the
  schedule's time zone, must be at least the setting.

### Web

- **Connections page.** Each connection that is not an upload gets a "Schedule" section with:
  - presets: "Nightly at 02:00", "Every 6 hours", "Weekly on Monday at 06:00", "Custom (cron)";
  - a time-zone select, defaulting to the browser's time zone;
  - an enabled switch;
  - "Next runs" showing the next three times in the user's local time;
  - "Last run" with its outcome and a link to the scan;
  - "Save" and "Remove schedule".

  Errors from the API (invalid cron, too frequent) appear next to the field. A 409 reloads the
  section with a notice.
- **Scans list.** Scheduled scans show a "scheduled" badge.

## Behaviour

1. **Saving.**
   1. The schedule is validated, then stored with `next_run_at` computed.
   2. Disabling it clears `next_run_at`. Enabling it computes `next_run_at` from now.
   3. Every save adds 1 to `version` and records `updated_by` (the actor, as in spec 007).
2. **Due runs** follow the job description above. Two workers, or a worker plus the inline API
   loop, cannot start the same run twice: `SKIP LOCKED` and the update of `next_run_at` in the
   same transaction prevent it.
3. **Scheduled scans** go through the same path as manual ones. They persist checks (spec 007),
   link findings (spec 009) and are reaped when interrupted (spec 008).
4. **Deleting a connection** deletes its schedule.
5. **Logging:**
   - `schedule.saved` (connection id, cron, time zone, enabled, actor);
   - `schedule.deleted`;
   - `schedule.ran` (connection id, outcome, scan id, next run).
6. **Safety.** Cron and time zone are validated strings and are never interpolated into SQL.
   Scheduled scans use the connection's read-only source like any scan (ADR-0006).

## Acceptance criteria

- [x] A connection gets a schedule through the API.
  - `next_run_at` and `next_runs` are correct in the given time zone, including across a
    daylight-saving change (test with `Europe/Zurich` around the last Sunday of October).
- [x] Running the due-schedule function with time moved past `next_run_at` creates one scan with
      `trigger = schedule`. The scan completes, and `next_run_at` moves to the next slot after
      now.
- [x] With a scan of the connection still running, a due schedule records `skipped_running` and
      starts nothing.
- [x] After a simulated three-day outage, one run happens, not three.
- [x] Two concurrent runs of the due-schedule function start exactly one scan.
- [x] Invalid cron, an unknown time zone, an interval below the minimum and an upload connection
      each return 422. A stale `version` returns 409.
- [x] Migration 0006 upgrades and downgrades, and `alembic check` is clean.
- [x] Web:
  - the schedule section saves, shows the next runs and removes;
  - API errors appear next to the field;
  - the scans list shows the "scheduled" badge.
- [ ] Staging: a nightly schedule on a connection produces a scan the next morning. This is the
      owner's check, done after deploy.
- [x] `make lint` and `make test` pass.

## Test cases

- **API, unit:**
  - next-run computation, including DST and the minimum interval;
  - cron validation.
- **API, integration (`api/tests/test_schedules.py`, database required):**
  - create, replace and delete, plus `stale_version`;
  - due runs with a frozen clock: pass `now` into the function rather than sleeping;
  - skip while a scan is running;
  - the outage collapses to one run;
  - concurrency, with two tasks;
  - the `trigger` field on scans;
  - an upload connection is refused;
  - 401 and 403 `csrf`.
- **Migration:** upgrade, `alembic check`, downgrade to 0005, upgrade again.
- **Web (`web/src/__tests__/Schedule.test.tsx`):**
  - presets fill the cron;
  - saving sends the CSRF header and version;
  - a 422 message appears at the field;
  - the next runs are shown;
  - removing;
  - the badge in the scans list.

## Implementation notes

- Daylight saving follows the wall clock: a repeated time fires once (its first occurrence), a
  skipped time fires after the jump (02:30 → 03:30 summer time), so nightly runs are 23 or 25
  hours apart on those days; croniter walks naive wall times, zoneinfo maps them to UTC.
- A due run inserts the scans and updates the schedules in one transaction, then starts the
  scans after the commit through `jobs.start_scan`, the function `POST /api/scans` and uploads
  use; a failed defer then turns `last_outcome` from `queued` into `failed_to_queue`.
- The due job does not bump `version` (only saves by people do), so a run never makes an open
  form stale. A `PUT` without `version` while a schedule exists, or with one when none
  exists, is 409 `stale_version` (`version` is the current one or null).
- `next_runs` starts at the stored `next_run_at` (which may be due already), then the two after
  it; 422 bodies are `{"detail", "field", "message"}`, `too_frequent` adds
  `min_interval_minutes` and `interval_minutes`; `GET /api/connections/{id}` carries `schedule` too.
- croniter's random (`R`) and hashed (`H`) fields and crons that never fire are `invalid_cron`.
- A due schedule whose next time cannot be computed (its zone dropped by a tzdata update, or a
  cron a newer croniter refuses) is disabled with `last_outcome = invalid_schedule` and logged
  as `schedule.invalid`, before any scan is created, so it cannot hold up the rest of the batch
  every minute (review of PR #10).
- A scheduled scan that cannot be handed to the runner after the batch commits (a database
  error) is failed with "failed to start" and its schedule records `failed_to_queue`; left
  queued, an inline scan would never run and its connection would skip every later slot.
- The `tzdata` package (Apache-2.0) is a dependency, so zoneinfo knows every IANA name whatever
  the image ships.
- Web: the schedule opens in a row below its connection ("Schedule" button), and the table
  gains a Schedule column; the next runs shown are the saved schedule's, computed by the API.

## Out of scope

- Several schedules per connection, or schedules for a subset of assets: later, if needed.
- Alerts when a scheduled scan's score drops or new findings appear: R2, sprint 8.
- S3 and other remote file sources: R2, sprint 7 (spec 002's note).
- Score history and the sparkline: spec 011.
