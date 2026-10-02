# Spec 007 — Assets, columns and checks persisted; lifecycle actions

Sprint 2, story S2-1. Depends on: spec 003 (checks, `CheckSpec`, scoring), spec 004 (API,
scan runner, migrations), spec 005 (asset report page), spec 006 (sign-in, CSRF header);
ADR-0005. Packages: `core/` (reconciliation of saved and generated checks), `api/`
(migration 0003, scan runner, `/api/assets`, `/api/checks`), `web/` (checks on the asset
report).

Status: approved 2026-10-02 by the owner; implemented in the same session as spec 006.

## Goal

Checks stop being regenerated from scratch on every scan. After a scan of a connection, each
asset, its columns and its checks are stored. The next scan of that connection starts from the
stored checks:

- **Locked** checks keep their parameters.
- **Retired** checks are not evaluated and are never created again.
- **Active and proposed** generated checks take fresh parameters from the new profile.
- **New** checks start as ADR-0005 says: rules `active`, baselines `proposed`.

On the asset report a signed-in user can approve, reject, lock, unlock, retire and restore a
check. Every change is recorded with who made it, and only `active` and `locked` checks
count toward scores and findings.

## User story

As a data owner, I lock the checks I agree with and retire the ones that do not apply, so
that the next scan judges my data by my decisions instead of starting over.

## Interface

### Core (`sahifa_core`)

- New module `checks/lifecycle.py` with one pure function:

  ```python
  def reconcile(generated: list[CheckSpec], saved: list[CheckSpec]) -> list[CheckSpec]
  ```

  It returns the checks to evaluate for one asset, keyed by `CheckSpec.id`
  (`type:asset:target`), using these rules:

  | Saved status | Generated now | Result |
  |---|---|---|
  | none | yes | the generated spec with its default status |
  | `proposed` or `active` (origin `generated`) | yes | the generated spec (new parameters), saved status |
  | `proposed` or `active` (origin `generated`) | no | dropped this scan (the column or condition is gone) |
  | `locked` | either | the saved spec unchanged |
  | `retired` | either | dropped (not evaluated, not re-created) |
  | origin `manual` | either | the saved spec unchanged |

- `run_scan(..., saved: Mapping[str, list[CheckSpec]] | None = None)` takes the saved checks
  per asset label; `evaluate_asset(ctx, saved)` evaluates `reconcile(generated, saved)`.
  `saved=None` keeps today's behaviour (CLI, uploads).
- A locked check whose column no longer exists is still returned by `reconcile`. It is not
  evaluated: it appears in `AssetReport.unevaluated` with reason `column_missing`, so the
  owner sees a stale lock rather than losing it silently.
- `ScanReport` gains `checks: list[CheckSpec]`: every reconciled spec, including the
  proposed ones and the unevaluated locked ones. The API persists from this list.

### Database (migration 0003)

| Table | Columns |
|---|---|
| `assets` | `id` uuid PK, `connection_id` → connections (cascade), `namespace` text, `name` text, `kind` (`table`, `view`, `file`), `row_count` bigint, `last_scan_id` → scans (set null), `created_at`, `updated_at`; unique (`connection_id`, `namespace`, `name`) |
| `columns` | `asset_id` → assets (cascade), `name` text, `position` int, `physical_type` text, `logical_type` text, `semantic_type` text null, `role` text; PK (`asset_id`, `name`) |
| `checks` | `id` uuid PK, `asset_id` → assets (cascade), `key` text (the core id), `type`, `column_name` text null, `columns` jsonb, `params` jsonb, `dimension`, `severity`, `kind` (`rule`, `baseline`, `manual`), `origin`, `status` CHECK (`proposed`, `active`, `locked`, `retired`), `max_fail_ratio` float, `version` int (+1 on every change), `last_scan_id` → scans (set null), `created_at`, `updated_at`; unique (`asset_id`, `key`); index (`asset_id`, `status`) |
| `check_events` | `id` uuid PK, `check_id` → checks (cascade), `at`, `user_id` → users (set null; null for the scanner), `action` (`created`, `regenerated`, `approve`, `reject`, `lock`, `unlock`, `retire`, `restore`), `from_status`, `to_status`, `params_before` jsonb null, `params_after` jsonb null; index (`check_id`, `at`) |

### API (all behind `current_user`; changes need the CSRF header)

| Route | Request | Response |
|---|---|---|
| `GET /api/assets?connection_id=&limit=&cursor=` | `limit` 1–200 (default 50) | `{"items": [{"id", "connection_id", "namespace", "name", "label", "kind", "row_count", "last_scan_id", "checks": {"proposed", "active", "locked", "retired"}}], "next_cursor"}`, ordered by label |
| `GET /api/assets/{id}` | — | the asset with `columns: [{"name", "position", "physical_type", "logical_type", "semantic_type", "role"}]`; 404 if unknown |
| `GET /api/checks?asset_id=&status=` | `asset_id` required; `status` optional, repeatable | `[{"id", "key", "type", "title", "column", "columns", "params", "dimension", "severity", "kind", "origin", "status", "max_fail_ratio", "version", "updated_at", "last_scan_id"}]` ordered by column, then type; 404 for an unknown asset |
| `POST /api/checks/{id}/{action}` | `action` ∈ `approve`, `reject`, `lock`, `unlock`, `retire`, `restore`; body `{"version": n}` | 200 the updated check; 404 unknown check; 409 `invalid_transition` (with `status`); 409 `stale_version` (with the current `version`); 422 without `version` |
| `GET /api/checks/{id}/events` | — | `[{"at", "user", "action", "from_status", "to_status", "params_before", "params_after"}]`, newest first; `user` is the email or `null` for the scanner |

Allowed transitions:

| Action | From | To |
|---|---|---|
| approve | `proposed` | `active` |
| reject | `proposed` | `retired` |
| lock | `active` | `locked` |
| unlock | `locked` | `active` |
| retire | `active` | `retired` |
| restore | `retired` | `active` |

### Web

- Asset report (`/scans/$scanId/assets/$asset`): a **Checks** section with tabs for
  Proposed, Active, Locked and Retired, showing counts. Each check row shows its title, column,
  parameters (a short readable form), severity and the latest result from this scan when
  there is one.
- Each row has the actions its status allows (table above). Buttons say what they do:
  "Approve", "Reject", "Lock", "Unlock", "Retire", "Restore".
- A 409 `stale_version` reloads the list and says "Someone changed this check; the list is
  up to date now."
- The page finds the asset through `GET /api/assets?connection_id=` and matches the report's
  asset label. Upload scans show the section too; their checks never carry over, because
  each upload is its own connection.

## Behaviour

1. **Loading saved checks.** When a scan of connection C starts, the runner loads the
   non-retired and retired checks of every asset of C, grouped by asset label, and passes
   them to `run_scan(saved=...)`. It also notes each check's `version`.
2. **Reconciliation.** For each asset the core reconciles the saved and generated checks as
   described in the Interface section, then evaluates the result. Proposed checks are
   evaluated and shown but do not score.
3. **Persisting.** The scan's success transaction also upserts:
   - each asset (by connection, namespace and name), with `row_count` and `last_scan_id`;
   - its columns, replacing the old set;
   - its checks, by (`asset_id`, `key`):
     - **new checks** are inserted, with a `created` event from the scanner;
     - **existing `active` and `proposed` generated checks** get the new `params`, `version` + 1
       and a `regenerated` event, but only when the parameters changed.

   The update only applies when the stored `version` still equals the version loaded in
   step 1. A user's change during the scan wins, and the scanner skips that check.
4. **Never touched by a scan:** `locked`, `retired` and `manual` checks keep their status and
   parameters, and the scanner never deletes a check.
5. **Lifecycle actions.** `POST /api/checks/{id}/{action}` runs in one transaction:
   1. Lock the check row (`SELECT … FOR UPDATE`).
   2. Compare its version with the request: a mismatch → 409 `stale_version`.
   3. Check the transition table: a forbidden transition → 409 `invalid_transition`.
   4. Set the new status, add 1 to `version`, set `updated_at`.
   5. Insert an event with the signed-in user's id.
   6. Return the check.

   In `dev` and `proxy` mode the event's `user_id` is null.
6. **Scores.** No change to the scoring rules. They already count only `active` and `locked`
   checks, and retired checks are no longer evaluated at all.
7. **Logging.** The API logs:
   - `check.changed` (check id, action, from and to status, user id);
   - `scan.checks_persisted` (scan id, inserted, regenerated, skipped because of a newer
     version).

   Parameter values are never logged, because they can contain values from the data
   (accepted-value sets).
8. **Safety.** Asset, column and check names are stored as text and only ever used as bound
   parameters; the hostile-name tests also run through persistence. Nothing writes to the
   source.

## Acceptance criteria

- [ ] `reconcile` follows the table for every row (unit tests, one per row).
- [ ] Scanning the faulty shop twice through a DuckDB connection stores its assets, columns and
      checks once. The second scan inserts nothing new and regenerates only checks whose
      parameters changed.
- [ ] **A locked check keeps its parameters across scans**, which is S2-1's "done when":
  - approve and lock `sah.accepted_values` on `orders.status` (a baseline, so it starts
    `proposed`);
  - add a new status value to the data and scan again;
  - the locked check still has the old value set and reports the new value as failing;
  - an active baseline on another column picked up its new parameters.
- [ ] A retired check is not evaluated, does not appear in the report and is not re-created.
- [ ] Each lifecycle action works from its allowed status and returns 409 `invalid_transition`
      from every other one. A stale `version` returns 409 `stale_version`.
- [ ] Every change writes one `check_events` row with the user. Scanner events have no user.
- [ ] A lock made while a scan runs survives that scan's persistence step.
- [ ] `alembic check` passes after migration 0003; downgrade to 0002 and upgrade again work.
- [ ] Web: the asset report lists checks by status, and each allowed action calls the API with
      the CSRF header and updates the list. A 409 `stale_version` reloads it.
- [ ] Hostile-name tests pass with persistence: asset and column names with quotes,
      semicolons and Unicode.
- [ ] `make lint` and `make test` pass.

## Test cases

- **Unit (`core/tests/test_lifecycle.py`):**
  - `test_new_generated_check_keeps_default_status`
  - `test_active_generated_takes_new_params`
  - `test_proposed_stays_proposed_with_new_params`
  - `test_active_not_generated_is_dropped`
  - `test_locked_keeps_saved_params`
  - `test_locked_with_missing_column_is_unevaluated`
  - `test_retired_is_never_evaluated_or_recreated`
  - `test_manual_is_kept`
- **Core integration (`core/tests/test_scan.py`):**
  - `test_saved_checks_change_the_report`: lock, retire and scan the faulty shop. The report
    reflects the saved statuses, and the scores ignore the retired checks.
- **API (`api/tests/test_checks.py`, database required):**
  - persistence after one scan, then idempotency after a second;
  - the locked-parameters scenario above;
  - every transition, allowed and refused;
  - `stale_version`;
  - events, with user and without (scanner);
  - a lock made between "load" and "persist" in a scan (the runner's persist step called with
    an older version);
  - 401 without a session and 403 `csrf` without the header;
  - list pagination;
  - hostile names.
- **Migrations:** upgrade, `alembic check`, downgrade to 0002 and upgrade again.
- **Web (`web/src/__tests__/Checks.test.tsx`):**
  - tabs and counts;
  - actions per status;
  - the CSRF header on POST;
  - the list refreshes after an action;
  - the `stale_version` message.

## Out of scope

- Editing parameters, severity or tolerance of a check (each check type needs a parameter
  schema): a later sprint 2 or sprint 3 story, after spec 011.
- Manual checks written by people (custom SQL, catalogue checks 11, 21, 23, 30): R2, sprint 8.
- Findings across scans with deduplication and status: spec 009.
- Roles: who may change checks. In R1 every user with access may; RBAC arrives in sprint 4
  (ADR-0010). The events table already records who did what.
- Saved checks in the CLI (`sahifa scan --checks file.json`): later, if wanted.
- History-based thresholds for baselines: sprint 5.
