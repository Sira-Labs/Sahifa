# Security baseline

The controls a Sahifa install must have before it sees real data (spec 012, story S3-1). Each
item is ticked with its evidence: a test, a file or a CI step. Open items name the sprint
that closes them. Review this list when a spec changes sign-in, uploads, sources or the
deployment.

Last reviewed: 2026-10-03, at release 0.1 (spec 012).

## Transport and headers

- [x] **TLS at the edge.** CapRover's nginx terminates TLS (`deploy/caprover.md`). The compose
      bundle's Caddy does when `SAHIFA_DOMAIN` is set (`deploy/caddy/Caddyfile`).
- [x] **HSTS.** `Strict-Transport-Security: max-age=31536000` from the web image
      (`test_caddyfile_sends_the_baseline_headers`).
- [x] **Strict CSP.** Scripts only from the app's own origin, no inline scripts, no
      `unsafe-eval`, `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'none'` (same
      test).
- [x] **Other browser headers.** `nosniff`, a strict referrer policy, `Permissions-Policy`
      without camera, microphone, geolocation, payment or USB, COOP and CORP `same-origin`,
      `X-Frame-Options: DENY`, and no `Server` header (same test). Checked live with Caddy
      2.10.2 in the PR.
- [x] **Caching.** Hashed assets are cached immutably and the HTML revalidates (same test).
- [x] **The API's own headers.** When the API is reached directly, every response has
      `no-store`, `nosniff`, `no-referrer`, `DENY` and `default-src 'none'`
      (`test_api_headers_are_added_and_route_values_kept`,
      `test_the_app_sends_headers_and_hides_docs_when_asked`).
- [x] **No API docs in production.** `/api/docs` and `/api/openapi.json` are off in prod
      unless `SAHIFA_API_DOCS` turns them on (same test).
- [x] **The Caddyfile parses.** `caddy validate` runs in the `web` CI job.

## Sign-in, sessions and CSRF (spec 006)

- [x] **Cookies.** Sessions use `__Host-` cookies that are `HttpOnly`, `Secure`,
      `SameSite=Lax` and `Path=/` (`test_full_login_per_method`).
- [x] **Session tokens.** The database holds an HMAC of each token, never the token
      (`test_session_hmac_lookup`).
- [x] **Expiry.** Idle and absolute session lifetimes apply (`test_idle_and_absolute_expiry`,
      `test_session_lifetimes_follow_the_settings`).
- [x] **Logout.** It revokes the session, and Keycloak's back-channel logout revokes by
      session id (`test_logout_revokes_and_returns_end_session`,
      `test_backchannel_logout_revokes_by_sid`).
- [x] **CSRF.** Unsafe requests need `X-Sahifa-Request: 1` and the install's origin
      (`test_csrf_header_and_origin`, `test_csrf_on_the_app`).
- [x] **Login flow.** It is single-use with PKCE, and `next` must be a relative path
      (`test_login_flow_is_single_use`, `test_pkce_challenge_matches_rfc_7636`,
      `test_next_param_is_relative_only`).

## Access

- [x] **Sign-in required.** Every route except health, version and the sign-in itself needs
      a signed-in user (`test_anonymous_requests`).
- [x] **Who gets in.** Only the admin and the allowed emails do; anyone else gets 403
      `no_access` (`test_unknown_email_gets_no_access`,
      `test_access_follows_admin_and_allowed_emails`).
- [x] **Production refuses weak settings.** It will not start with dev sign-in, placeholder
      secrets, or proxy mode without a declared gate (`test_prod_refuses_dev_mode`,
      `test_prod_refuses_placeholder_password`, `test_prod_oidc_refuses_missing_or_placeholder`,
      `test_prod_proxy_needs_the_gate`).
- [ ] **Roles within an install** (viewer, editor, admin): R2, the Tabayyun authz model
      (ADR-0010).

## Uploads

- [x] **Size, count and type.** Limits apply per file (`SAHIFA_MAX_UPLOAD_MB`), per request
      (`SAHIFA_MAX_UPLOAD_TOTAL_MB`, enforced while the body streams and before it is parsed),
      per file count, and to an extension allowlist
      (`test_declared_body_over_the_limit_is_refused_at_once`,
      `test_streamed_body_is_cut_off_at_the_limit`,
      `test_uploads_are_checked_before_and_after_arrival`, `test_upload_rejects_bad_files`).
- [x] **Content matches the extension.** Parquet must have its magic bytes, and text files
      must not be binary (`test_content_matches`).
- [x] **File names.** Names from the browser are reduced to their base name, without control
      or bidirectional characters, at most 200 characters (`test_clean_file_name`). Files are
      stored under random names.
- [x] **Free disk.** An upload that would leave less than `SAHIFA_MIN_FREE_DISK_MB` free is
      refused before it is read (`test_low_disk_refuses_an_upload_before_reading_it`).
- [x] **Clean-up.** Upload folders are deleted after `SAHIFA_UPLOAD_TTL_DAYS`. The clean-up
      refuses paths outside the upload directory and never follows symlinks (`test_clean_uploads`).

## Rate limits

- [x] **Token buckets.** Per session, or per address when no session is sent:
  - sign-in flow: 20 per minute;
  - scans: `SAHIFA_RATE_SCANS_PER_HOUR` (60);
  - writes: 120 per minute;
  - reads: 1,200 per minute.

  Over the limit the answer is 429 with `Retry-After` (`test_rate_limiter_spends_and_refills`,
  `test_rate_limit_answers_429_with_retry_after`,
  `test_scans_per_hour_and_the_off_switch`).
- [x] **The real client address.** Caddy trusts `X-Forwarded-For` only from private ranges,
      and so does uvicorn (`api/docker-entrypoint.sh`). The API app is not exposed publicly on
      CapRover (`deploy/caprover.md`, section 2).
- [ ] **Limits shared across API replicas:** today each process counts on its own. Closed when
      the API scales out (R3).

## SQL and sources (ADR-0006)

- [x] **Read-only sessions.** Source sessions are read-only, with statement and lock timeouts
      (`test_postgres_session_is_read_only`).
- [x] **No values in SQL text.** Identifiers are quoted by SQLGlot, and no data value is ever
      concatenated into SQL (`test_scan_survives_hostile_names`,
      `test_hostile_names_through_persistence`).
- [x] **Masked examples.** Example values of personal semantic types are masked
      (`test_personal_examples_are_masked`, `test_mask`).

## Secrets

- [x] **No secrets in the repository.** Configuration comes from the environment; source
      credentials are only `SAHIFA_CONN_*` references (ADR-0006); secrets are `SecretStr`
      settings, never logged.
- [ ] **Secret scanning in CI** (gitleaks or GitHub push protection): sprint 4.

## Logging

- [x] **Structured logs.** JSON lines through structlog; rate limits are logged with the
      bucket and key kind, never the address or session.

## Dependencies

- [x] **Known vulnerabilities fail CI.** `pip-audit` (core, api) and `pnpm audit` (high and
      critical, production) fail CI unless an advisory is accepted in
      `security/audit-ignore.toml` with a reason and an expiry date
      (`test_audits_fail_on_findings_not_accepted`,
      `test_audit_ignores_need_a_reason_and_expire`).
- [x] **Updates.** Dependabot opens update PRs (`.github/dependabot.yml`).
- [x] **Image scanning.** The release images are scanned with Trivy, and fixable critical CVEs
      fail the release (`.github/workflows/release.yml`).

## Licences (ADR-0008, ADR-0015)

- [x] **Allowlist.** The `licences` CI job checks the runtime dependencies of core, api and web
      against `security/licences.toml`. The only exceptions are psycopg, psycopg-binary and
      psycopg-pool (LGPL-3.0, ADR-0015) (`test_policy_exceptions_and_skips`,
      `test_the_repository_policy_allows_only_the_adr_exceptions`).

## Containers and supply chain

- [x] **API and worker.** They run as the non-root user `sahifa` (uid 10001,
      `api/Dockerfile`).
- [x] **Build provenance.** Images are built with an SBOM and provenance, and promoted to
      production by digest (ADR-0012).
- [ ] **The web image's Caddy runs as root.** It needs a non-root user with
      `CAP_NET_BIND_SERVICE` and writable `/data` and `/config`: sprint 4.
- [ ] **No signature check at deploy.** CapRover deploys verify no image signature: R2, with
      the production server.
