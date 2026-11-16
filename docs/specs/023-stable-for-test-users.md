# Spec 023 — Stable for test users: error references, versions, backup, data note, feedback

Sprint 4b, story S4b-4. Depends on: spec 012 (security middleware), spec 015 (release 0.1,
image tags), spec 021 (quick start), spec 022 (error texts), ADR-0012 (staging and promotion),
ADR-0016 (nightly runs: no approval step). Packages: `api/`, `web/`, `deploy/`, `docs/`.

Status: written and implemented by the nightly run of 17 November 2026 (ADR-0016).

## Goal

A test user runs Sahifa on their own machine for weeks. When something breaks, the person at
the screen sees a reference, and whoever runs the install finds the error under that reference
in the API's log. They know which version they run and how to stay on it, how to back the
install up and bring it back, what happens to the files they upload, and where to say what
does not work.

## User story

As the operator of a test install, I get a reference from a user who saw an error, search the
API's log for it and see the request and the stack trace, so that I can fix it or report it
with the version I run.

## Interface

### API: a reference on every answer

| | |
|---|---|
| Response header | `X-Request-ID` on every HTTP answer of the API, errors and the answers of the limits (413, 429, 507) included |
| Request header | `X-Request-ID` from the caller is kept when it is 8 to 64 characters of `A-Z a-z 0-9 . _ -`; anything else is replaced by a new one (32 hex characters) |
| Unexpected error | `500` with JSON `{"detail": "internal_error", "message": "<a sentence>", "request_id": "<the reference>"}` |
| Log, unexpected error | one line `api.error` with `request_id`, `method`, `path` (no query string), `error` (the exception's type), `detail` (its text, 300 characters) and the stack trace |
| Log, an answer of 500 or above without an exception | one line `api.error` with `request_id`, `method`, `path`, `status` |
| Log, every other line written while a request is handled | carries `request_id` |

### Web

| Where | What |
|---|---|
| every `ErrorPanel` for a status of 500 or above with a reference | a line *Reference* with the reference, and what to do with it |
| footer | `Sahifa <version> (<commit, 7 characters>) · schema <revision>`, a link *Feedback* and a link *Your data* |
| `/scans/new`, tab *Upload files* | one sentence on where the files go and when they are deleted, with the link *Your data* |

### Documents

| File | Content |
|---|---|
| `docs/guides/backup-and-restore.md` | what to back up, the commands for the compose bundle, restore on the same and on a new machine, a restore test |
| `docs/guides/your-data.md` | what Sahifa reads, what it keeps, what it deletes and when, what leaves the install (nothing) |
| `deploy/quickstart.md` | choosing and keeping a version, updating, going back, finding an error by its reference, feedback |

## Behaviour

1. **The reference.** A new middleware, `RequestIdMiddleware`, wraps everything except the
   security headers: the limits, the CSRF guard and the routes run inside it. It takes the
   caller's `X-Request-ID` when it has the accepted form, else makes one, and puts it on the
   answer.
2. **Unexpected errors.** An exception that no handler took is logged as `api.error` and
   answered with the 500 above. When the answer has already started (a stream), the error is
   logged and raised again, as before. Cancellation is not an error and passes through.
3. **Logged context.** `request_id` is bound for the time of the request (structlog context
   variables), so lines written by the routes carry it. A scan started inline keeps the
   reference of the request that started it on its lines, next to `scan_id`.
4. **What is not logged.** No query string, no body, no header other than the reference: a
   path holds ids, not data.
5. **The panel.** `ApiError` carries the reference of the answer. `ErrorPanel` shows it for a
   status of 500 or above; the advice for 500 becomes "look in the API's log for the reference
   below". Other statuses show no reference: their message says what is wrong, and the operator
   has nothing to look up.
6. **The footer** shows the version, the commit the image was built from (7 characters; left
   out when the image does not know it) and the schema revision. *Feedback* opens the
   project's issue chooser on GitHub in a new tab; *Your data* opens the data note.
7. **Versions.** Nothing new is built: `release.yml` already publishes `<version>` for a `v*`
   tag, `sha-<7 characters>` for every commit on `main` (never moved) and `latest`. The quick
   start now says which to take: a released version, or the `sha-` tag of the commit the footer
   shows, and never `latest` for an install that should stay as it is. It says how to update
   (change `SAHIFA_TAG`, `pull`, `up -d`; the API migrates on start) and that going back to an
   older image after a migration needs the backup from before the update.
8. **Backup.** The database holds everything worth keeping; the guide backs it up with
   `pg_dump` in the custom format through the `db` container, and `.env` and
   `compose.override.yaml` by copying them, under names with the time to the second; the dump gets its name only when `pg_dump`
   succeeded.
   Uploaded files and Caddy's certificates are not backed up: the first are deleted after
   `SAHIFA_UPLOAD_TTL_DAYS` anyway, the second are issued again.
9. **Restore** reads the dump's table of contents first (`pg_restore --list`), so a missing
   or broken file stops it before the database is dropped. It then stops `api` and `worker`, replaces the database with the dump (`pg_restore`),
   and starts them with an image as new as the dump or newer; the steps are chained, so a
   failed one stops the rest. On a new machine the bundle is
   started once first, so the roles exist. The CI job `quickstart` runs backup and restore
   after its scans and checks that the scans are still there.

## Acceptance criteria

- [x] Every API answer has `X-Request-ID`; an accepted one from the caller is echoed, any other
      replaced.
- [x] A route that raises answers 500 `internal_error` with `request_id`, and the log has
      `api.error` with the same reference, the path and the exception's type.
- [x] The 500 answer has the security headers.
- [x] `ErrorPanel` shows the reference for 500 and above and not for 403 or 404.
- [x] The footer shows version, commit and schema, *Feedback* and *Your data*.
- [x] The upload tab says where files go and links the data note.
- [x] The quick start names the version to install and how to update and go back.
- [x] The CI job `quickstart` backs up, restores and finds its scans again.
- [x] `make lint` and `make test` clean.

## Test cases

Unit and integration (`api/tests/test_requests.py`):
- `test_every_answer_has_a_reference`: an answer and a 404 carry the header, each its own.
- `test_callers_reference_is_kept_or_replaced`: a good one is echoed; too short, too long and
  one with a space or a line break are replaced.
- `test_unexpected_error_is_answered_and_logged`: a route that raises gives 500 with the body
  above, the security headers, and `api.error` in the log with reference, method, path, type.
- `test_error_status_without_exception_is_logged`: a route answering 503 is logged with its
  status.
- `test_limits_answer_with_a_reference`: a 413 from the body limit carries the header.
- `test_an_error_after_the_answer_started_is_logged_and_raised`: a stream that breaks.
- `test_the_app_answers_with_a_reference`: the real app echoes a proxy's reference and puts
  one on its own 413.

Unit (`web/src/__tests__`):
- `api.test.ts`: `ApiError.requestId` from the answer's header, null without one;
  `errorReference` for 500 and above only.
- `NewScan.test.tsx`: the reference on a 500 and none on a 413; the sentence and the link on
  the upload tab.
- `ScansList.test.tsx`: footer text and both links; `format.test.ts`: `versionLine`.

CI (`.github/scripts/quickstart-check.sh`): backup, restore, the scans are still listed.

## Decisions

- **No error-tracking service** (Sentry or the like): it needs an account and sends data out
  of the install, which a self-hosted test must not do by default. The log line with the
  reference is the report; a tracker is S12-3.
- **The reference is shown for 500 and above only.** For a refused or invalid request the
  message is the answer, and a reference would send people to a log that has no line for it.
- **The caller's reference is accepted** in a narrow form, so a proxy in front of Sahifa can
  set one and both logs line up; anything else is replaced, so nothing odd reaches the log.
- **The feedback link is fixed** (the GitHub issue chooser), not a setting: test users report
  to the project. An install that wants its own address can be given a setting later.
- **No release is tagged by this spec.** `v*` tags are the owner's (CONTRIBUTING.md, the
  release-tags ruleset). Until the next one, test users pin the `sha-` tag of a commit.
- **Backup by `pg_dump`, not by copying the volume:** it works while the bundle runs and
  across Postgres minor versions, and the same file restores on a new machine.

## Out of scope

- Point-in-time recovery, encrypted off-site backups, a restore drill for production: S12-3.
- Request ids in the audit log, and on the worker's job lines (they carry `scan_id`).
- A setting for the feedback address; sending feedback from inside the app.
- Tagging a release.
