# Spec 019 — Security follow-ups: secret scanning in CI, Caddy as a non-root user

Sprint 4, story S4-5. Depends on: spec 012 (security baseline and its open items), ADR-0008
(licences), ADR-0012 (release pipeline). Packages: `.github/`, `web/Dockerfile`, `deploy/`,
`docs/`.

Status: approved 2026-10-10 by the owner; done.

## Goal

Spec 012 left two items open in `docs/security/baseline.md`. When this spec is done, both are
closed:
- **Secrets.** CI fails when a commit adds something that looks like a secret.
- **The web container** runs Caddy as an unprivileged user, like the API and the worker do
  already, and still serves on ports 80 and 443.

## User story

As the administrator of a Sahifa install, I can trust that no credential slips into the
repository unnoticed and that a flaw in the web server does not hand out root in its container.

## Interface

### Secret scanning (CI job `secrets`)

- **The tool:** gitleaks, MIT licensed, a pinned release (8.24.3).
  - It is downloaded from its GitHub release in CI and checked against a SHA-256 written in the
    workflow.
  - It is not a runtime dependency, so ADR-0008 does not apply. The repository's licence check
    covers runtime dependencies only.
- **What it scans:** the whole git history (`gitleaks git`, full checkout), with gitleaks'
  default rules and `--redact`, so a found value never reaches the CI log.
- **Known false positives** go in `.gitleaksignore`, one fingerprint per finding, with a comment
  saying why. A fingerprint names the commit, file, rule and line, so a new secret in the same
  file is still found. Today there are three, all fake values in `api/tests/test_settings.py`.
- **Self-test.** `.github/scripts/secret-scan-selftest.sh` checks that the scan catches what it
  should:
  1. It creates a throw-away git repository.
  2. It commits a token in the shape of a GitHub token, generated at run time, so no such
     value is ever in this repository.
  3. It asserts that gitleaks exits with "leaks found".
  4. It asserts that the same scan of a clean commit passes.

  The `secrets` job runs the self-test before the real scan.

### The web image

- **The user.** Caddy runs as the user `sahifa`, uid and gid 10001, the same as the API image.
- **Ports.** `/usr/bin/caddy` keeps the file capability `cap_net_bind_service`, set again in
  the Dockerfile, so it binds 80 and 443 without root. Nothing changes for CapRover or the
  compose bundle.
- **Writable directories.** `/data` (certificates) and `/config` (Caddy's autosaved
  configuration) belong to 10001. Everything else stays read-only to it: `/srv` (the SPA) and
  `/etc/caddy/Caddyfile` are owned by root.
- **Existing compose installs.** Their `caddy_data` volume was created by a root Caddy.
  - A one-shot service, `web-volume`, in `deploy/compose.yaml` changes the volume's owner to
    10001 before `web` starts (`depends_on: condition: service_completed_successfully`).
  - It runs as root, does only that, and exits. The web container itself never runs as root.

### CI job `web-image`

On every pull request and push to `main`, CI builds `web/Dockerfile` without pushing it, then:
1. starts the image;
2. asserts that every process in the container runs as uid 10001 (`docker top`);
3. asserts that `GET /version.json` answers 200 on the container's port 80, with the security
   headers of spec 012;
4. asserts that the image's configured user is `10001:10001` (`docker inspect`).

## Behaviour

1. **A commit with a secret.** The `secrets` job fails and names the file, the line and the
   rule. The value itself is redacted. The way out is to remove the secret from the history
   and rotate it; a fingerprint in `.gitleaksignore` is only for values that are not secrets.
2. **The web container.** It starts as 10001, binds 80 (and 443 with `SAHIFA_DOMAIN`), and
   writes certificates to `/data`. It cannot write to `/srv` or to the Caddyfile.
3. **Upgrading a compose install.** `docker compose up -d` runs `web-volume` once per start,
   then `web`. No manual step is needed.
4. **CapRover.** The web app has no persistent directory, so nothing changes there.

## Acceptance criteria

- [x] CI fails on a committed test secret: the self-test shows it in every run.
- [x] The repository's full history passes the scan, with the three fingerprints in
      `.gitleaksignore`, each with a reason.
- [x] The web image runs as non-root: CI's `web-image` job checks the user of every process
      and serves `/version.json` on port 80.
- [x] The compose bundle upgrades an existing `caddy_data` volume without a manual step.
- [x] `docs/security/baseline.md` ticks both items, naming the checks. Spec 012's open-items
      line points here.
- [x] Staging serves the web app after the deploy, with the same headers as before.
      Checked after the merge (2464d68): identical headers, web, api and worker on the commit.
- [x] `make lint` and `make test` pass.

## Test cases

- **CI, job `secrets`:**
  - the self-test: a leak found in a throw-away repository with a generated token, and a
    clean pass of a clean commit;
  - the real scan of the full history.
- **CI, job `web-image`:**
  - the process user, the image's configured user;
  - `/version.json` with a 200 and the CSP header.
- **By hand, after the merge:**
  - staging's `/` and `/api/version` answer, and the response headers are unchanged;
  - `docker compose config` accepts the bundle.

## Implementation notes

- **The self-test reads the report, not only the exit status.** gitleaks exits 1 both for
  findings and for errors, so the self-test asserts the `github-pat` rule in the JSON report;
  a gitleaks that cannot run does not pass as "found".
- **A fingerprint names one commit and line.** A later commit that changes one of those test
  values is a new finding and needs its own fingerprint or a different value.
- **Why `web-volume` is needed.** The base image's `/data/caddy` is world-writable, but the
  certificates, keys and directories a root Caddy wrote inside are not. `web-volume` uses the
  web image itself (as root, entrypoint `chown`), so there is no extra image to pull.
- **The check runs the bundle's own service.** `web-image-check.sh` starts `web-volume` from
  `deploy/compose.yaml` on a volume prepared as a root Caddy would leave it. It then starts
  Caddy with `SAHIFA_DOMAIN=localhost`, which binds 443 and writes a local CA to the volume as
  10001. That goes beyond the four checks above.
- **Required checks.** `secrets` and `web image` are added to `.github/rulesets/protect-main.json`.
  A repository admin applies the file to the live ruleset (CONTRIBUTING.md).
- **Locally the full image build fails behind a TLS-intercepting proxy** (pnpm cannot verify
  the registry). The final stage was built from a local SPA build and checked with the same
  script; CI builds the whole Dockerfile.

## Out of scope

- Image signature checks at deploy: R2, with the production server (spec 012).
- GitHub push protection. It is a repository setting, which the owner can turn on next to
  this check; the CI job works without it.
- Pre-commit hooks for developers. The CI job is the gate.
