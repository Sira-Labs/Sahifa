# Spec 001 — Repository scaffold, CI, release and deploy pipeline

Sprint 1, story S1-1. Depends on: ADR-0008, ADR-0012. Packages: repository root, `.github/`,
`deploy/`, `core/`, `api/`, `web/` (build files only).

## Goal

The repository builds, tests and lints three packages in CI, publishes two images to GHCR on
every push to `main`, and deploys them to the CapRover staging apps once the owner has set up
the `staging` environment. Before that the deploy job is a no-op and the run stays green.

## User story

As the platform admin, I push to `main` and the commit is running on staging without manual
steps, and I can promote exactly that build to production after approving it.

## Interface

- Packages: `core/` (`sahifa-core`, uv, Python ≥ 3.11, console script `sahifa`), `api/`
  (`sahifa-api`, package `sahifa`, depends on `../core` by path), `web/` (pnpm 10, Node 22).
- `Makefile` targets: `lint`, `test`, `fmt`, `demo`, `dev-infra`, `api-dev`, `web-dev`,
  `db-upgrade`, `db-revision m=…`.
- Workflows: `ci.yml` (jobs `core`, `api` with a `postgres:17` service, `web`),
  `release.yml` (source gate, images, Trivy, immutable `sha-<short>` tags, `deploy-staging`),
  `promote.yml` (digest promotion to `production` behind the required reviewer),
  `.github/scripts/wait-live.sh`.
- Images: `ghcr.io/sira-labs/sahifa-api` (FastAPI, migrations on start, `SAHIFA_ROLE=api`),
  `ghcr.io/sira-labs/sahifa-web` (Caddy serving the SPA and `version.json`, proxying `/api`
  and `/healthz` to `SAHIFA_API_UPSTREAM`). Build arg `SAHIFA_COMMIT`.
- `deploy/`: `compose.yaml`, `compose.dev.yaml`, `.env.example`, `caprover.md`, `README.md`,
  `caprover/{api,web}/captain-definition`.

## Behaviour

1. A pull request runs `ci`; all three jobs must pass.
2. A push to `main` runs `ci` and `release`. `release` builds both images by digest, scans
   them with Trivy (fixable critical CVEs fail), tags them, then `deploy-staging` deploys
   when `vars.CAPROVER_SERVER` is set on the `staging` environment and waits until
   `<CAPROVER_WEB_URL>/version.json` and `/api/version` report the commit.
3. A `v*` tag on a commit outside `main` fails `release` before anything is published.
4. `promote.yml` with a commit checks it is on `main` and live on staging, resolves the
   `sha-<short>` tags to digests, waits for approval, deploys the digests to production and
   waits until production serves the commit.

## Acceptance criteria

- [ ] `make lint` and `make test` pass locally.
- [ ] `ci` passes on the first push to `main`.
- [ ] `release` publishes `sahifa-api` and `sahifa-web` with `sha-<short>`, `main` and
      `latest` tags; `deploy-staging` logs "CAPROVER_SERVER not set" and succeeds.
- [ ] `docker compose -f deploy/compose.yaml up` with a generated `.env` serves the web app
      on port 80 and `GET /api/version` through it.

## Test cases

CI itself is the test. Locally: `docker build -f api/Dockerfile .` and
`docker build -f web/Dockerfile .` succeed from the repository root.

## Out of scope

- The worker image role and its CapRover app: spec 008.
- Licence audit in CI: sprint 3 (S3-1).
