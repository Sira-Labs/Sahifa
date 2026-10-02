# ADR-0012: Staging and production on separate CapRover servers

- **Status:** Accepted (adopts the Sīra family decision, Arqam ADR-0020, Tabayyun ADR-0016)
- **Date:** 2026-10-02
- **Deciders:** owner

## Decision

- The **staging-and-tools server** (the current Hetzner CapRover) runs `sahifa-db-stg`,
  `sahifa-api-stg`, `sahifa-web-stg` (later `sahifa-worker-stg`) at
  `sahifa-stg.siralabs.org`, with test data only.
- The **production server** (Germany) runs `sahifa-db`, `sahifa-api`, `sahifa-web` (later
  `sahifa-worker`) at `sahifa.siralabs.org`, real people's data only there.
- `release.yml` builds, scans (Trivy) and publishes `ghcr.io/sira-labs/sahifa-api` and
  `sahifa-web` on every push to `main`, tags them `sha-<short>` (immutable), and deploys
  staging. `promote.yml` deploys the **same digests** to production after the owner's approval
  on the `production` environment. Both wait until the new commit is live.
- Separate secrets per environment; CapRover tokens live on GitHub environments, not at
  repository level; `v*` tags only from `main`, created by organisation admins.
- Production backups before the first real user: WAL archiving plus nightly `pg_dump -Fc`,
  encrypted, in another Hetzner location; timed restore drills into a throwaway database.

## Consequences

Steps are in `deploy/caprover.md`. Until the owner sets `CAPROVER_SERVER` on the `staging`
environment the deploy job is a no-op, so CI can run before CapRover is ready.
