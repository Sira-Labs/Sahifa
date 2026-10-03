# Spec 009 — Findings across scans: deduplication, occurrences, status

Sprint 2, story S2-3. Depends on: spec 004 (scan persistence, `findings` per scan), spec 006
(sign-in, CSRF header, actor), spec 007 (persisted checks, events pattern), spec 008 (scans in
the worker); domain model, "Finding rules". Packages: `api/` (migration 0005, scan
persistence, `/api/findings`), `web/` (findings across scans, status actions).

Status: approved 2026-10-03 by the owner.

## Goal

Today every scan writes its own findings, so the same broken column shows up once per scan.
After this spec:

- **One finding per check.** A failing check has exactly one finding that is not resolved.
  Each scan where the check fails again counts as an **occurrence** of that finding.
- **Automatic resolution.** A check that passes again resolves its finding. If it fails later,
  the same finding reopens.
- **Status by people.** A signed-in user can acknowledge, resolve, mute (optionally until a
  date) or reopen a finding, with a short note. Every change is recorded.
- **Cross-scan list.** A new `/findings` page lists the findings of all scans, by default only
  those still needing attention.

## User story

As a data owner, I see each problem once with how often and since when it occurs, mark the
ones I am handling or accept, and trust that a fixed problem disappears by itself, so that
the findings list stays a to-do list instead of a log.

## Interface

### Database (migration 0005)

| Table | Columns |
|---|---|
| `finding_occurrences` | The existing `findings` table, **renamed**: one row per failing check per scan, with its evidence, exactly as today. New column `finding_id` → `findings` (set null), null for scans from before this migration. Index (`finding_id`, `scan_id`). |
| `findings` (new) | `id` uuid PK, `check_id` → checks (cascade), `status` CHECK (`open`, `acknowledged`, `resolved`, `muted`), `severity` (from the latest occurrence), `occurrences` int, `first_scan_id`, `last_scan_id` → scans (set null), `first_seen_at`, `last_seen_at`, `resolved_at` null, `resolved_scan_id` null, `muted_until` timestamptz null, `version` int, `created_at`, `updated_at`. Partial unique index: one row per `check_id` where `status <> 'resolved'`. Index (`status`, `severity`). |
| `finding_events` | `id` uuid PK, `finding_id` → findings (cascade), `at` (`clock_timestamp()`), `user_id` → users (set null), `actor` text not null (email, or `scanner`, `dev`, `proxy`), `action` CHECK (`opened`, `recurred`, `auto_resolved`, `reopened`, `unmuted`, `acknowledge`, `resolve`, `mute`, `unmute`, `reopen`), `from_status`, `to_status`, `note` text null (at most 1000 characters). Index (`finding_id`, `at`). |

Occurrences from before migration 0005 keep `finding_id` null and are not backfilled. Their
scans had no persisted checks, so they cannot be matched reliably.

### API (behind `current_user`; changes need the CSRF header)

| Route | Request | Response |
|---|---|---|
| `GET /api/findings` | Query parameters: `connection_id`, `asset_id`, `status` (repeatable; default `open`, `acknowledged`, `muted`), `severity` (repeatable), `limit` 1–200 (default 50), `cursor` | `{"items": [...], "next_cursor"}`. Each item: `{"id", "status", "severity", "occurrences", "first_seen_at", "last_seen_at", "muted_until", "version", "check": {"id", "key", "type", "title", "status", "column"}, "asset": {"id", "label", "connection_id"}, "latest": {"scan_id", "summary", "failed", "evaluated", "ratio", "low", "high", "dimension"}}`. Ordered by severity (critical first), then `last_seen_at` descending, then `id`. |
| `GET /api/findings/{id}` | — | The item above, plus `occurrences_list` (the latest 20: scan id, time, failed, evaluated, ratio, interval, summary, examples, SQL, next step) and `events` (newest first: at, actor, action, from and to status, note). 404 for an unknown id. |
| `POST /api/findings/{id}/{action}` | `action` ∈ `acknowledge`, `resolve`, `mute`, `unmute`, `reopen`. Body `{"version": n, "note": "…"?, "until": "<ISO time>"?}`; `until` is only allowed with `mute` and must be in the future. | 200 with the updated item. 409 `invalid_transition` (with `status`). 409 `stale_version` (with `version`). 422 for a note over 1000 characters, `until` in the past, or `until` with another action. |
| `GET /api/scans/{id}/findings` | unchanged | Each item gains `finding_id` and `finding_status` (null for occurrences from before 0005). |

Allowed transitions for people:

| Action | From | To |
|---|---|---|
| acknowledge | `open` | `acknowledged` |
| resolve | `open`, `acknowledged`, `muted` | `resolved` |
| mute | `open`, `acknowledged` | `muted` |
| unmute | `muted` | `open` |
| reopen | `resolved` | `open` |

### Web

- **New `/findings` page**, linked in the navigation.
  - Filters for status (by default open, acknowledged and muted), severity and connection.
  - Each finding is shown as a card with:
    - the summary sentence, the check title, asset and column;
    - a severity chip and a status chip;
    - "seen N times, first … last …";
    - a mute end date, when muted;
    - action buttons named for what they do: "Acknowledge", "Resolve", "Mute…", "Unmute",
      "Reopen".
  - "Mute…" asks for an optional end date and a note. The other actions offer an optional note.
  - A 409 `stale_version` reloads the list with a short notice.
  - Pages through results with "Load more".
- **Finding detail**, on the same page as an expandable panel or at `/findings/$id`: the
  occurrences, with examples (masked where personal), the SQL and the next step, plus the
  event history.
- **Scan findings page** (`/scans/$id/findings`): each item shows its finding's status chip and
  links to the finding.

## Behaviour

1. **Linking at persistence.** In the scan's success transaction, after spec 007 has persisted
   the checks, each finding the core reported is matched to its check by
   `(asset, CheckSpec.id)`. The core only reports findings for `active` and `locked` checks
   that fail beyond their tolerance. For each matched finding:
   1. **A non-resolved finding exists for the check.** Add 1 to `occurrences`, set
      `last_scan_id` and `last_seen_at`, and take the severity from this occurrence. If it is
      `muted` and `muted_until` has passed, it becomes `open` with an `unmuted` event from the
      scanner. Otherwise it keeps its status and gets a `recurred` event.
   2. **Otherwise, the check's most recent resolved finding exists.** It becomes `open`:
      `occurrences` + 1, `resolved_at` cleared, a `reopened` event from the scanner.
   3. **Otherwise.** A new `open` finding with `occurrences` 1 and an `opened` event.

   The occurrence row (`finding_occurrences`) gets that finding's id.
2. **Automatic resolution.** In the same transaction, every non-resolved finding whose check
   was evaluated in this scan **and passed** becomes `resolved`, with `resolved_scan_id` and
   an `auto_resolved` event from the scanner.
   - A check that was not evaluated this scan leaves its finding unchanged: it was retired,
     proposed, unevaluated or dropped (spec 007), or its asset failed.
3. **Changing data.** Scanner changes add 1 to `version`, like people's changes, so a person
   acting on a stale view gets 409 `stale_version` instead of overwriting the scanner's
   result.
4. **People's actions.** Each action runs in one transaction:
   1. Lock the row (`SELECT … FOR UPDATE`).
   2. Check the version, then the transition.
   3. Set the status. `resolve` sets `resolved_at` (`resolved_scan_id` stays null). `mute`
      sets `muted_until` (null means indefinitely). `unmute` and `reopen` clear it.
   4. Add 1 to `version`.
   5. Insert an event with the user, the actor and the note.

   In `dev` and `proxy` mode the actor is `dev` or `proxy` and `user_id` is null.
5. **Concurrency.** Scan persistence locks the findings it changes. Uniqueness comes from the
   partial unique index: an insert racing with another scan of the same connection retries as
   case 1.1.
6. **Scores are unchanged.** Muting or acknowledging a finding does not change any score;
   scores follow the checks (ADR-0004). The scan summary's `finding_counts` stay per scan.
7. **Logging.** The API logs `finding.changed` (finding id, action, from and to status, user
   id) and `scan.findings_linked` (scan id, opened, recurred, reopened, auto-resolved). Notes
   and evidence are never logged.
8. **Safety.** Notes are plain text: stored as is, rendered as text (never HTML), and limited
   to 1000 characters. Nothing writes to a source.

## Acceptance criteria

- [ ] **A rescan does not duplicate findings** (S2-3's "done when"). Scanning the faulty shop
      twice through one connection gives the same number of findings as the first scan. Each
      has `occurrences` 2 and two occurrence rows.
- [ ] After fixing the data behind one finding and scanning again:
  - that finding is `resolved` with an `auto_resolved` event;
  - the others have `occurrences` 3.
- [ ] Breaking the data again reopens the same finding (same id, `reopened` event); it does not
      create a new one.
- [ ] Each person's action works from its allowed statuses and returns 409
      `invalid_transition` otherwise. A stale `version` returns 409 `stale_version`.
- [ ] A finding muted with a past `until` (set directly in the test) becomes `open` at the next
      failing scan, with an `unmuted` event. Without `until` it stays `muted`.
- [ ] Findings of a retired check, and of a check not evaluated in a scan, are left unchanged
      by that scan.
- [ ] `GET /api/findings` filters by status, severity, connection and asset, pages with a
      cursor, and defaults to open, acknowledged and muted.
- [ ] Migration 0005 renames `findings` to `finding_occurrences` without losing rows. It
      downgrades back to 0004 with the rows intact, and `alembic check` is clean.
- [ ] Web:
  - `/findings` lists, filters and pages;
  - each action sends the CSRF header and updates the card;
  - `stale_version` reloads;
  - the scan findings page shows status chips and links.
- [ ] `make lint` and `make test` pass.

## Test cases

- **API (`api/tests/test_findings.py`, database required):** real scans of the faulty shop
  through a DuckDB connection. Use the same `connect`/`scan` helpers as `test_checks.py`; data
  is changed between scans by rewriting a CSV. Tests:
  - the rescan, auto-resolve and reopen sequence;
  - every transition;
  - `stale_version`;
  - mute with and without `until`;
  - a retired check leaves its finding alone;
  - list filters and cursor;
  - notes over 1000 characters return 422;
  - events with user and actor;
  - 401 and 403 `csrf`.
- **Migration:** upgrade, row count kept, `alembic check`, downgrade to 0004 with rows intact,
  then upgrade again.
- **Web (`web/src/__tests__/FindingsAcross.test.tsx`):**
  - list and default filters;
  - actions per status, including mute with a date;
  - the CSRF header;
  - the `stale_version` reload;
  - the detail with occurrences and events;
  - the status chip and link on the scan findings page.

## Out of scope

- **Assigning findings to people, comments threads, notifications:** alerts are R2, sprint 8.
- **Organisation-scoped access:** sprint 4 (RBAC). Until then every user with access sees and
  changes all findings.
- **Score history and sparklines:** spec 011.
- **Backfilling occurrences from before migration 0005:** not done.
- **Bulk actions on many findings:** later, if wanted.
