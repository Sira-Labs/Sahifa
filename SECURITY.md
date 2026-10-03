# Security policy

Sahifa connects to other people's databases and file stores, so we treat security reports
seriously. A leaked connection string or a query that writes to or locks a source would do
more harm than any quality problem Sahifa finds (ADR-0006).

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting:
<https://github.com/Sira-Labs/Sahifa/security/advisories/new>.

Include the affected component (core, api, web, deploy), a version or commit, steps to
reproduce, and impact. You should hear back within 5 working days. We will keep you informed
while we triage, fix and publish an advisory, and credit you unless you prefer not.

## Supported versions

Sahifa is pre-1.0. Only the `main` branch and the most recent `v*` tag receive fixes.

## Scope

In scope: the code in this repository, the published container images
(`ghcr.io/sira-labs/sahifa-api`, `ghcr.io/sira-labs/sahifa-web`) and the compose bundles in
`deploy/`. Out of scope: the data stores you connect Sahifa to and third-party services you
integrate, except where Sahifa's use of them is at fault; findings that require a compromised
host or administrator credentials.

## Design notes for reporters

- No secrets in the repository; configuration comes from environment variables and production
  refuses placeholder values.
- Source credentials are never stored in Sahifa's database or logs: a connection holds the
  name of a `SAHIFA_CONN_*` environment variable (ADR-0006). A credential that reaches the
  database, a log line, a report or an API response is always in scope.
- Sources are read in read-only transactions with statement and lock timeouts. Anything that
  makes Sahifa write to a source, or run SQL built from data or user input as text (SQL
  injection through identifiers, values or uploaded files), is always in scope.
- Uploads are limited in size (per file and per request, enforced while the body streams),
  count, extension and content, stored under random names with cleaned display names, and
  deleted after a TTL; path traversal or reading files outside the upload directory is in
  scope.
- Example values of personal semantic types (email, phone, IBAN, VAT ID) are masked in
  reports; an unmasked value is in scope.
- People sign in through Keycloak (spec 006, ADR-0010): HttpOnly `__Host-` session cookies, a
  CSRF header on every unsafe request, only the admin and allowed emails get access. Installs
  without sign-in sit behind HTTP basic auth at the proxy, which production requires to be
  declared.
- Requests are rate-limited per session or address, and the API sends its own security
  headers.
- Images are built with SBOM and provenance attestations and scanned with Trivy; known
  vulnerabilities (`pip-audit`, `pnpm audit`) and licences outside ADR-0008 fail CI.

The full list of controls, each with its evidence, is the
[security baseline](docs/security/baseline.md).
