# Spec 012 — Security baseline

Sprint 3, story S3-1. Depends on: spec 004 (uploads, scans), spec 006 (sign-in, CSRF,
sessions), spec 008 (worker), ADR-0006 (read-only sources, credentials), ADR-0008 (licences).
Packages: `api/` (middleware, settings, upload checks), `deploy/caddy/` (headers, proxies),
`.github/workflows/ci.yml`, `.github/scripts/security_policy.py` and `security/` (audits),
`docs/security/`.

Status: approved 2026-10-03 by the owner; psycopg's LGPL-3.0 allowed by ADR-0015.

## Goal

The release 0.1 install meets a written security baseline, `docs/security/baseline.md`. Every
item is ticked with its evidence (a test, a file or a CI step), or is listed as a follow-up
with its sprint.

Four gaps found while writing this spec are closed:
1. **Missing headers.** There is no HSTS, the static assets have no cache policy, and the API
   sets no headers of its own when it is reached directly.
2. **Uploads checked only after arrival.** The request body is read in full before the
   per-file limit is checked, so a huge upload fills the disk before it is refused. There is
   no total limit across files, no check that the content matches the file type, and no
   free-disk guard.
3. **No rate limits.**
4. **Advisory-only dependency checks.** `pip-audit` and `pnpm audit` run in CI but never fail
   it, and nothing checks licences.

## User story

As the operator, I can show that a Sahifa install withstands the usual web attacks and ships
only dependencies we may ship, so that I can put it in front of real data with a clear
conscience.

## Interface

### Settings (prefix `SAHIFA_`)

| Name | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_TOTAL_MB` | `1024` | The largest upload request, all files together. The per-file `MAX_UPLOAD_MB` (200) stays. |
| `MIN_FREE_DISK_MB` | `1024` | An upload is refused with 507 when the data directory would have less free space than this after it. |
| `RATE_LIMITS` | `on` | `off` turns rate limiting off, for example behind a gateway that already limits. |
| `RATE_SCANS_PER_HOUR` | `60` | Scans one user may start per hour, manual and uploaded. |
| `API_DOCS` | `on` outside prod, `off` in prod | Serves `/api/docs` and `/api/openapi.json`. |

### Headers

**Caddy (web image),** in addition to today's CSP, `nosniff`, referrer, permissions and
COOP headers:
- `Strict-Transport-Security: max-age=31536000`. Browsers ignore it over plain HTTP.
- `Cross-Origin-Resource-Policy: same-origin`.
- `X-Frame-Options: DENY`, for old browsers; the CSP already has `frame-ancestors 'none'`.
- `Permissions-Policy` extended with `payment=()` and `usb=()`.
- `Cache-Control: public, max-age=31536000, immutable` on `/assets/*`, whose names are hashed.
- `Cache-Control: no-cache` on the SPA's HTML.
- Global `trusted_proxies static private_ranges`, so the client address from CapRover's nginx
  reaches the API (logs and rate limits) instead of nginx's own address.

**API,** on every response unless the route set its own:
- `Cache-Control: no-store`;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`;
- `X-Frame-Options: DENY`;
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`. When `API_DOCS` is on,
  the docs pages are exempt.

### Request size

A middleware limits request bodies:
- `POST /api/scans/upload`: at most `MAX_UPLOAD_TOTAL_MB`.
- Every other route: at most 1 MB.

A declared `Content-Length` over the limit is refused at once. A body without one is counted
as it streams and cut off at the limit. Either way the answer is
`413 {"detail": "too_large", "limit_mb": n}`, sent before the multipart parser writes more to
disk.

### Upload checks (`POST /api/scans/upload`)

All of today's checks stay: the file count, the extension allowlist, the per-file size and
random storage names. In addition:

1. **Content matches the extension**, checked on the first bytes: a Parquet file starts and
   ends with `PAR1`, and a CSV, TSV, JSON or NDJSON file has no NUL byte in its first 8 KB.
   Otherwise `415 {"detail": {"code": "content_mismatch", "file": name, "message": …}}`.
2. **File names** are reduced to their base name. Control characters are removed and the name
   is capped at 200 characters, both where it is stored and where it is shown.
3. **Free disk.** When the declared size would leave less than `MIN_FREE_DISK_MB` free under
   the data directory, the upload is refused with `507 {"detail": "insufficient_storage"}`.
   This is checked before any byte is written.

### Rate limits

Token buckets kept in the process, keyed by the session (its cookie, hashed), or by the client
address when no session is sent:

| Bucket | Routes | Limit |
|---|---|---|
| `auth` | `GET /api/auth/login`, `/api/auth/passkey/add`, `/api/auth/callback` | 20 per minute per address |
| `scans` | `POST /api/scans`, `POST /api/scans/upload` | `RATE_SCANS_PER_HOUR` per user |
| `write` | other `POST`, `PUT`, `DELETE` under `/api` | 120 per minute |
| `read` | `GET` under `/api` | 1,200 per minute |

`/healthz`, `/api/version` and the back-channel logout are not limited. Over the limit, the
answer is `429 {"detail": "rate_limited", "retry_after": s}` with a `Retry-After` header, and a
`rate.limited` line is logged (bucket, key kind, route; never the address in full). The
buckets live in one API process; several API replicas each count on their own (documented).

### CI audits

- **Python vulnerabilities:** `pip-audit` fails the `python core` and `python api` jobs on any
  known vulnerability, except IDs listed with a reason and an expiry date in
  `security/audit-ignore.toml`.
- **npm vulnerabilities:** `pnpm audit --prod --audit-level high` fails the `web` job, with
  the same ignore file.
- **Licences:** `.github/scripts/security_policy.py` (standard library only) reads the
  runtime dependencies of core and api (a `uv sync` without dev extras) with their licence
  metadata, and the web
  production dependencies (`pnpm licenses list --prod --json`). It fails on any licence
  outside the allowlist in `security/licences.toml`: MIT, MIT-0, BSD-2/3-Clause, Apache-2.0,
  ISC, PSF-2.0, MPL-2.0, 0BSD, Unlicense, and OFL-1.1 for fonts. Exceptions are listed per
  package with a reason; psycopg, psycopg-binary and psycopg-pool (LGPL-3.0) are allowed by
  ADR-0015. It runs in a new `licences` job.

### Docs

- `docs/security/baseline.md`: the checklist, grouped as transport and headers, sessions and
  CSRF, access, uploads, rate limits, SQL and sources, secrets, logging, dependencies,
  licences and containers. Each item has its evidence.
- `SECURITY.md` links to it.
- `deploy/caprover.md` gets a note on nginx's `client_max_body_size` for uploads.

## Behaviour

1. **Limits are checked before work starts.** Request size and free disk come first, then the
   rate limit, and only then is the multipart body parsed. An upload refused for any of these
   leaves no folder behind.
2. **Errors from the new checks** (413, 415, 429, 507) use the JSON shape above. The web shows
   their message in its existing error panel; a 429 says "Too many requests, try again in
   N s".
3. **The audits fail CI only on new problems.** An entry in an ignore file needs a reason and
   an expiry date; an expired entry fails the job.
4. **Nothing changes for sources.** Sessions stay read-only with timeouts (ADR-0006).

## Acceptance criteria

- [x] Caddy sends the new headers. A test parses the Caddyfile for each header, and `caddy
      validate` runs in CI on the web image.
- [x] The API sends its headers on JSON responses and on errors. `/api/docs` is off in prod.
- [x] An upload over `MAX_UPLOAD_TOTAL_MB` gets 413 without the body being read in full: both
      with `Content-Length` and chunked. The upload folder does not remain.
- [x] A disguised file (a CSV named `.parquet`, a binary named `.csv`) gets 415. A hostile file
      name is stored and shown cleaned.
- [x] Low free disk gets 507 before any write.
- [x] Each bucket answers 429 with `Retry-After` past its limit; `/healthz` is never limited;
      `RATE_LIMITS=off` turns it off.
- [x] The client address behind CapRover's proxy is the real one: Caddy's `trusted_proxies`,
      with a test of the key function.
- [x] CI fails on a known vulnerability or a licence outside the allowlist; both are shown by
      a test of the script on fixtures. The current dependencies pass.
- [x] `docs/security/baseline.md` is complete, every item ticked or listed as a follow-up.
- [x] `make lint` and `make test` pass.

## Test cases

- **API (`api/tests/test_security.py`):**
  - the headers;
  - docs on and off;
  - the body limit, with `Content-Length` and chunked;
  - content mismatch;
  - file-name cleaning;
  - free disk (with `shutil.disk_usage` patched);
  - each rate bucket and the key function, with a fake clock;
  - the exemptions;
  - `RATE_LIMITS=off`.
- **Script (`api/tests/test_security_policy.py`):**
  - allowed, denied and excepted licences;
  - expression parsing (`MIT OR Apache-2.0`, classifiers);
  - expired ignore entries.
- **Web:** the 429 message.

## Implementation notes

- Rate limits key on the session cookie (hashed), not the user id: the check runs as ASGI
  middleware before FastAPI reads an upload, where the user is not yet known without a
  database lookup. A forged cookie gets its own bucket but only reaches 401s; every route that
  does work needs a valid session.
- FastAPI turns a body cut off mid-parse into a 400, so the size middleware drops whatever the
  app answers once the limit is passed and sends its own 413.
- uvicorn trusts `X-Forwarded-For` from private networks only (was `*`), overridable with
  `FORWARDED_ALLOW_IPS`; Caddy has `trusted_proxies static private_ranges`, without which the
  API saw CapRover's nginx as every client.
- The content check refuses UTF-16 text as binary (NUL bytes); the reader takes UTF-8 only,
  and the message says so.
- The licence script prefers PEP 639 `License-Expression`, then licence classifiers (several
  are alternatives), then a short `License` field; python-dateutil's field says only "Dual
  License".
- psycopg's LGPL-3.0 was found by the new licence job; ADR-0015 allows it (owner, 2026-10-03).
- The 415 for a content mismatch keeps FastAPI's `detail` with a code, the file and a message,
  which the web shows; the other new errors are `{"detail", "message", …}` at the top level.

## Out of scope

- Caddy as a non-root user, image signing checks at deploy, and secret scanning in CI: listed
  as follow-ups in the baseline.
- Rate limits shared across several API replicas (Postgres- or Redis-backed): when the API
  scales out (R3).
- A web application firewall, and DDoS protection beyond these limits: the operator's edge.
- Penetration test by a third party: before 1.0.
