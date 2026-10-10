# Spec 018 — Audit log of changes

Sprint 4, story S4-4. Depends on: spec 007 (check lifecycle), spec 009 (finding status), spec
010 (schedules), spec 016 (workspaces, roles, row-level security), spec 017 (role matrix).
Packages: `api/` (model, migration 0009, service, router), `web/`, `docs/`.

Status: approved 2026-10-10 by the owner; done.

## Goal

Every change a person makes in Sahifa is recorded in one place: who, what, when, in which
workspace, and the state before and after. Workspace admins read their workspaces' log on a
page; the org admin reads all of it. Nobody, the API included, can change or delete an entry.

## User story

As the administrator of a Sahifa install, I can see who locked a check, muted a finding or
changed a schedule, and what it was before, so that I can explain a change in the scores and
answer an auditor.

## Interface

### Database (migration 0009)

**Table `audit_events`:**

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | |
| `at` | timestamptz | `clock_timestamp()`, the time of the change |
| `workspace_id` | uuid → workspaces | the workspace the change belongs to; never null |
| `user_id` | uuid → users, `ON DELETE SET NULL` | the person, when signed in |
| `actor` | text | the email, or `dev` / `proxy` without sign-in (as in `check_events`) |
| `action` | varchar(40) | one of the actions below |
| `object_type` | varchar(20) | `check`, `finding`, `schedule`, `connection`, `scan`, `workspace`, `membership` |
| `object_id` | uuid | the object; for a membership, the member's user id |
| `summary` | text | one line for people, e.g. `Locked "Range" on orders.amount` |
| `before`, `after` | jsonb, nullable | the fields that changed, before and after |

**Rules on the table:**
- It is under row-level security like the other workspace-owned tables (spec 016).
- It is **append-only**. A trigger refuses `UPDATE` and `DELETE` for every role, the owner
  included. The only exception is the cascade when a workspace is deleted (S4-3), which the
  trigger allows through a transaction-local setting that only the deletion sets.
- Indexes: `(workspace_id, at DESC)`, `(action)` and `(user_id)`.

**Backfill.** The migration copies the existing history into the log:
- every `check_events` row whose actor is not `scanner`;
- every `finding_events` row whose action is a person's (acknowledge, resolve, mute, unmute,
  reopen).

The time, actor, workspace, before and after are kept.

### Actions

Only people's changes are recorded. What the scanner does on its own (new findings, automatic
resolving, generated checks) stays in the object's own history, as today.

| Action | Object | before / after |
|---|---|---|
| `check.approve`, `check.reject`, `check.lock`, `check.unlock`, `check.retire`, `check.restore` | check | `status`, `version` |
| `finding.acknowledge`, `finding.resolve`, `finding.mute`, `finding.unmute`, `finding.reopen` | finding | `status`, `muted_until`, `note` (after only) |
| `schedule.saved`, `schedule.deleted` | schedule | `cron`, `timezone`, `enabled`, `sample_rows` |
| `scan.started`, `scan.uploaded` | scan | after: connection, sample rows, files (names only) |
| `connection.created` | connection | after: name, kind, secret reference name (never its value) |
| `connection.moved` | connection | `workspace` (id and name); one entry in each workspace |
| `workspace.created`, `workspace.renamed` | workspace | `name` |
| `membership.added`, `membership.changed`, `membership.removed` | membership | `role`, plus the member's email |

**Atomic with the change.** The entry is written in the same transaction as the change. When
the change rolls back, so does its entry, and a change cannot commit without its entry.

### API

`GET /api/audit` lists entries, newest first.

**Who may read it:**
- The admin of a workspace reads that workspace's entries.
- The org admin reads all entries.
- Anyone else gets 403 `forbidden_role`. A person who is admin of A and viewer of B sees only
  A's entries.

**Query parameters:**
- `workspace_id`, `action` (exact action, or a prefix like `check.`), `actor` (email,
  substring);
- `object_type` with `object_id`;
- `since` and `until` (ISO times);
- `cursor`, and `limit` (default 50, at most 200).

**Response:** `Page[AuditEntry]`, where each entry is `{id, at, workspace: {id, name}, actor,
action, object_type, object_id, summary, before, after}`. The cursor is `(at, id)`.

The role matrix (spec 017) gains the operation as a `list` with minimum role `admin`.

### Web

- **A page `/audit`**, linked in the header for workspace admins and the org admin next to
  "Workspaces".
  - A table: time, person, workspace (when the person sees more than one), what happened (the
    summary), and before → after for the changed fields.
  - Filters: workspace (the header filter), kind of change (checks, findings, schedules,
    scans, connections, workspaces, members), and person.
  - "Load more".
- **Links.** Each entry links to its object where it still exists: a check's asset, a finding,
  a connection's schedule, a scan.

## Behaviour

1. **Recording.** Every route that changes something calls one service function, `audit.record`,
   before it commits. The route passes the action, the workspace, the object, a summary, and
   the changed fields before and after.
2. **Secrets never reach the log.** The fields recorded for each action are listed in the
   table above, and nothing else is recorded. A credential reference is recorded by its
   variable name only. Data examples are never recorded.
3. **Reading.** Row-level security limits the entries to the caller's workspaces. The route
   narrows them further to the workspaces where the caller is admin, or keeps all of them for
   the org admin.
4. **Append-only.** `UPDATE` or `DELETE` on `audit_events` fails, for the API's role and for the
   table owner. A test shows both.
5. **Moving a connection** writes one entry in the old workspace and one in the new, so both
   admins see it.
6. **Logging.** The structured logs of spec 016 (`membership.changed` and others) stay. The
   audit log is for people; the structured logs are for operators.

## Acceptance criteria

- [x] Approving a check and muting a finding each appear in `GET /api/audit` with the actor,
      the time, and status before and after (the sprint plan's "done when").
- [x] Every action in the table is recorded by its route, in the same transaction. A change
      whose commit fails leaves no entry.
- [x] Workspace admins see only their workspaces' entries. Editors and viewers get 403. The
      matrix of spec 017 covers the route.
- [x] `UPDATE` and `DELETE` on `audit_events` fail for the API role and the owner.
- [x] Migration 0009 backfills the people's check and finding events, is reversible, and
      `alembic check` is clean.
- [x] No secret value or data example appears in any entry. A test scans every recorded
      entry for the test credential's value.
- [x] The web page lists, filters and pages entries for an admin, and is not linked for
      others.
- [x] `make lint` and `make test` pass.

## Test cases

- **API, `tests/test_audit.py`:**
  - one test per action: make the change, then find exactly one entry with the expected
    action, actor, workspace, before and after;
  - a rollback: a change that fails (409 stale version) records nothing;
  - append-only: `UPDATE` and `DELETE` refused, through the API's session and through the
    owner engine;
  - reading: admin of A only, admin of A and viewer of B, org admin, filters and cursor;
  - no secret: set `SAHIFA_CONN_*` to a value with a marker, create the connection, and
    check that no entry's JSON holds the marker;
  - migration: upgrade from 0008 with check and finding events, check the backfill,
    downgrade, upgrade again.
- **API, `tests/test_matrix.py`:** `GET /api/audit` in `OPS`.
- **Web:**
  - the page renders entries with before → after;
  - the filters send their query parameters;
  - "Load more" works;
  - no link for a viewer.

## Implementation notes

- **A deleted user's entries stay.** `ON DELETE SET NULL` clears `user_id`; the trigger lets
  exactly that update through, and the entry keeps the actor's email.
- **The purge setting.** `sahifa.audit_purge` is transaction- or session-local. Today only the
  tests' clean-up uses it, to remove the workspaces they create; workspace deletion (S4-3) will
  use it too.
- **A new workspace's entry.** The request's scope does not hold the new workspace, so the route
  widens it (`db.add_to_scope`). It also flushes the workspace before recording: the entry has no
  ORM relationship that would order the two inserts, and a taken name must still answer 409.
- **No entry without a change.** Setting a member's role to the role they already have records
  nothing.
- **The connection's config is not recorded,** only its name, kind and the credential's variable
  name: the config is free-form and could hold anything.
- **Backfilled summaries** name the check type (`sah.range`) and the asset without the core's
  quoting of dotted names. New entries name the catalogue title (“Range”).
- **The role matrix** knows that an outsider without the admin role is refused the audit list
  (403), unlike the lists editors may read.

## Out of scope

- Sign-ins, sign-outs and failed sign-ins in the audit log. They have no workspace; they stay
  in the structured logs (spec 006). They could come with an org-level log in R3.
- Exporting the log (CSV) and keeping it for a set time with deletion. R3, together with a
  retention setting.
- Recording the scanner's own changes. They stay in each object's history.
- Deleting workspaces and invitations: S4-3.
