# Spec 022 — First run: demo data, a guided first scan, empty states, error texts

Sprint 4b, story S4b-3. Depends on: spec 004 (uploads and scans), spec 005 (web), spec 008
(upload clean-up), spec 016 (workspaces and roles), spec 017 (role matrix), spec 018 (audit
log), ADR-0016 (nightly runs: no approval step). Packages: `api/`, `web/`, `docs/`.

Status: written and implemented by the nightly run of 15 November 2026 (ADR-0016).

## Goal

A person who opens a fresh install reaches a first report without reading the docs. The empty
start page says what Sahifa does in three steps and offers two ways in: the person's own data,
or a demo shop that is scanned with one click. While the scan runs the page says what is
happening; the demo report says what it shows. Where a page is empty or a request fails, the
text says what to do next.

## User story

As a data engineer trying Sahifa for the first time, I click one button and get a report on
demo data within a minute, so that I see what Sahifa finds before I point it at my own data.

## Interface

### API: `POST /api/scans/demo`

Starts a scan of the demo shop: the synthetic web shop of `sahifa_core.synth` with its faults.

| | |
|---|---|
| Request body | optional JSON `{"workspace_id": "<uuid>"}`; the body may be absent |
| Role | editor of the workspace (the same rule as an upload, `Access.pick`) |
| Success | `202` with a `Scan`, as `POST /api/scans/upload` returns |
| Errors | `403` for a viewer, `404` for a workspace the caller does not see, `409 workspace_required` when the caller may upload to several workspaces and names none |

`Scan` gets one new field, on every route that returns a scan:

| Field | Type | Meaning |
|---|---|---|
| `demo` | boolean | the scan reads the demo shop |

The audit log gets one new action, `scan.demo` (object `scan`; after: connection, sample rows,
files by name).

### Web

| Where | What |
|---|---|
| `/` with no scans | three numbered steps, a primary button *Try the demo data* and a second button *Scan your own data* (to `/scans/new`) |
| `/scans/new`, tab *Upload files* | a line *No files at hand?* with a button *Scan the demo data* |
| scans list, report head | the source of a demo scan reads *Demo data* |
| `/scans/$scanId` while queued or running | the steps of a scan, with the current one marked |
| `/scans/$scanId` of a demo scan | a note on what the demo shop is and what to do next |
| `/scans/$scanId` of a failed scan | the reason and, for known reasons, what to do |
| every `ErrorPanel` | a second line with what to do, where the status says it |
| `/findings` with nothing to show | a link to start a scan |

## Behaviour

1. **Demo scan.** `POST /api/scans/demo` picks the workspace first (`Access.pick(workspace_id,
   "editor")`), so a refused request writes nothing.
2. It writes the faulty shop with `write_shop(folder, rows=5000)` into a new folder
   `uploads_dir/<batch>/`, in a thread. The shop's dates are relative to the moment it is
   written, so "dates in the future" fires whenever the demo is run.
3. It creates the connection `upload-<batch>` of kind `upload` with
   `config = {paths, names, files, demo: true}` in the picked workspace and starts a scan that
   reads every row (`sample_rows = 0`), through the same hand-off as an upload (`_enqueue`,
   `jobs.start_scan`), in inline and in queue mode.
4. The audit entry is `scan.demo` with the summary "Started a scan of the demo data".
   The request counts against the scan rate limit, and is refused with 507 when the uploads
   folder would fall below the free-disk reserve (`SAHIFA_MIN_FREE_DISK_MB`) with the demo's
   files (counted as 2 MB), as an upload is.
5. If writing the files or creating the connection fails, the folder is removed and the error
   propagates (500). A folder left by a later failure has no scan and goes with the clean-up.
6. The folder is an upload folder like any other: the clean-up job of spec 008 deletes it
   `SAHIFA_UPLOAD_TTL_DAYS` after its scan finished. The report, findings and checks stay.
7. `Scan.demo` is true exactly when the scan's connection is an upload whose config has
   `demo: true`.
8. **Start page.** With no scans, the page shows the three steps (*Point Sahifa at data*, *It
   profiles and checks every table*, *Read the report*) and the two buttons. *Try the demo
   data* posts to `/api/scans/demo` and opens the new scan's page. With several workspaces
   the person may upload to, the request names one: the filtered workspace, else the default
   one, else the first (the rule of the upload form). A viewer sees the button disabled with
   the reason. A failure shows an `ErrorPanel` with *Retry*.
9. **New scan.** The upload tab offers the same action below the drop zone; it uses the
   workspace picked in the form.
10. **Running.** The scan page lists the steps *Waiting for a free slot*, *Profiling every
    table and running the checks*, *Scoring and writing the report* and marks the current one
    from the scan's status (`queued` → first, `running` → second).
11. **Demo note.** A succeeded demo scan shows, above the score, that this is a synthetic web
    shop with faults put in on purpose, and links to `/scans/new` for the person's own data.
12. **Failed scans.** Below the reason, the page says what to do when the reason matches a
    known pattern (case-insensitive):

    | Reason contains | Advice |
    |---|---|
    | `has no source` | the connection's variable is not set on the API: set it and restart the API |
    | `connection refused`, `could not connect`, `could not translate host name`, `timeout expired` | the database cannot be reached from the API: check host, port and firewall |
    | `password authentication failed`, `permission denied` | the login was refused or may not read: check the user, the password and its `SELECT` rights |
    | `statement timeout`, `canceling statement` | a query ran into the time limit: scan fewer rows per table |
    | `no such file`, `no files` | the files are gone: uploads are deleted after a few days, upload them again |
    | anything else | fix the source and start a new scan (as today) |
13. **Error texts.** `errorAdvice(error)` returns one sentence for these statuses, and
    `ErrorPanel` shows it below the message:

    | Status | Advice |
    |---|---|
    | 0 | check that the API is running and reachable (`docker compose ps`), then retry |
    | 403 | ask an admin of the workspace for the editor role, or pick another workspace |
    | 413 | split the files, or raise `SAHIFA_MAX_UPLOAD_MB` on the API |
    | 415 | accepted are CSV, TSV, Parquet and JSON lines, text as UTF-8 |
    | 429 | wait a minute, then retry |
    | 502, 503, 504 | the API is starting or down: check its container and logs, then retry |
    | 500 | look at the API's log for this time; retrying may work |
    | 507 | free disk space on the server, or lower `SAHIFA_UPLOAD_TTL_DAYS` |

    Other statuses get no second line: their message already says what is wrong.
14. **Findings.** `/findings` with no finding and no filter says that findings appear after a
    scan and links to `/scans/new`.
15. **The API is down.** When `/api/auth/me` fails with anything but 401 (sign in) or the 403
    of an address without access, the page shows one `ErrorPanel` (*Sahifa could not check
    your session*) with the message, the advice and *Retry*, and asks once. A later check
    that fails while the session is known keeps the page (and a half-filled form). Before, the app
    rendered anyway and every component asked for the session again, thousands of times a
    minute against an API that was already failing (found on a database without migrations).

## Acceptance criteria

- [x] `POST /api/scans/demo` returns 202; the scan succeeds with `demo: true`, six assets and
      findings, among them `sah.future_dates`.
- [x] A viewer gets 403 and nothing is written; another workspace's demo scan is invisible
      (role matrix, `test_every_route_is_classified` green).
- [x] The audit log has `scan.demo` for the scan.
- [x] The demo folder is deleted by the upload clean-up once its scan is older than the TTL.
- [x] Other scans have `demo: false`.
- [x] The empty start page shows the steps and both buttons; *Try the demo data* posts and
      opens the scan; a viewer cannot click it.
- [x] The scan page marks the current step, shows the demo note on a demo report and advice
      for a failed scan with a known reason.
- [x] `ErrorPanel` shows advice for the statuses above and none for the others.
- [x] A failing `/api/auth/me` shows the panel and is asked once until *Retry*.
- [x] Deleting a workspace that holds a scanned upload with findings works (see Decisions).
- [x] `make lint` and `make test` clean.

## Test cases

Integration (`api/tests/test_workspaces.py`): `test_deleting_a_workspace_with_a_scanned_demo`.

Integration (`api/tests/test_demo.py`):
- `test_demo_scan_round_trip`: 202, `demo` true, succeeds, six assets, `sah.future_dates`
  among the findings, the files are in the uploads folder, `scan.demo` in the audit log.
- `test_demo_folder_is_cleaned_up`: after the scan is aged past the TTL, `clean_uploads`
  removes the folder and the report still loads.
- `test_other_scans_are_not_demo`: an uploaded scan has `demo` false.

Role matrix (`api/tests/test_matrix.py`): `POST /api/scans/demo`, editor, kind `create`.

Unit (`web/src/__tests__`):
- `ScansList.test.tsx`: the empty page has the steps and both buttons; the demo button posts
  and navigates; a viewer's button is disabled; a failure shows the panel; a failing session
  check shows the panel and is asked once.
- `NewScan.test.tsx`: the upload tab's demo button posts with the picked workspace.
- `Report.test.tsx`: steps while running, the demo note, advice on a failed scan.
- `api.test.ts`: `errorAdvice` per status; `format.test.ts`: `scanSource` of a demo scan,
  `scanFailureAdvice` per pattern.

## Decisions

- No switch to turn the demo off: it is an upload like any other, needs the editor role, is
  small (about 1 MB) and is deleted by the upload clean-up.
- No step-by-step overlay ("tour"): the guide is the empty page, the running steps and the
  demo note, which also work for a person who comes back later.
- 5,000 rows: the size the tests use, where every rule check fires; the scan takes seconds.
- The demo reads every row, so its intervals have zero width; the note says that a sample
  widens them.

- **Found while testing: a workspace with a scanned upload could not be deleted** (spec 020).
  A finding of a real scan points at that scan as first and last seen. Deleting the
  connection set both to NULL and deleted the finding's check in one statement; Postgres then
  re-checks the twice-updated finding against the deleted check and refuses. The tests of
  spec 020 built their findings with one scan reference, so they passed. `delete_workspace`
  now deletes the workspace's findings first; `test_deleting_a_workspace_with_a_scanned_demo`
  covers it. No migration: the foreign keys are right for every other path.
- The role matrix has 33 workspace operations now (spec 017 counted 32).
- The matrix test scans a demo of 200 rows and waits for its scans before the workspaces are
  dropped; the product's demo stays at 5,000.

## Out of scope

- Versioned images, error reporting with request ids, backup guide, data note, feedback link:
  S4b-4.
- A demo Postgres source: staging's optional demo source is an owner item (sprint plan).
- Translating the web app.
