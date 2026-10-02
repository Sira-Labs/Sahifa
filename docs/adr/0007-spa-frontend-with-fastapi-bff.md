# ADR-0007: SPA frontend served by Caddy, FastAPI as backend-for-frontend

- **Status:** Accepted (adopts Tabayyun ADR-0005)
- **Date:** 2026-10-02
- **Deciders:** owner

## Decision

Vite + React 19 + TypeScript SPA with TanStack Router and Query and Tailwind v4, built into a
static bundle served by Caddy with security headers (CSP without inline scripts, HSTS when
behind TLS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`). Caddy proxies
`/api` and `/healthz` to the API, so the browser talks to one origin and the session cookie
(R2) is first-party. The SPA writes `version.json` with the commit so deploys can be verified.
The visual language follows the Sahifa product page (`site/index.html`): Bricolage Grotesque,
Figtree, IBM Plex Mono, the lapis-ink palette, light and dark themes.

## Consequences

Same toolchain as Tabayyun (pnpm, Node 22 LTS, vitest), so components and the CI job can be
shared. Server-side rendering is not needed: every page sits behind sign-in from R2.
