# ADR-0010: Identity through a Keycloak realm, BFF cookie sessions, workspace RBAC

- **Status:** Accepted (adopts Tabayyun ADR-0006, ADR-0007 and spec 013)
- **Date:** 2026-10-02
- **Deciders:** owner

## Decision

Sign-in through a Keycloak realm `sahifa` with Google, GitHub and passkeys, no passwords;
Authorization Code with PKCE handled by the API (backend-for-frontend), a `__Host-` session
cookie, CSRF header, back-channel logout. Org → workspace → connection RBAC in Postgres with
row-level security. Arrives in R2 (sprint 4). Until then staging is protected by CapRover's
HTTP basic auth on the web app, and `SAHIFA_ENV=prod` refuses to start without
`SAHIFA_ACCESS_GATE=basic-auth-at-proxy` set, so an unprotected production install is a
deliberate choice.

## Consequences

The Tabayyun auth package is the template; shared code moves into a common library once a
third product needs it.

## Update 2026-10-02: sign-in pulled forward to sprint 2 as spec 006

Sign-in (Keycloak realm `sahifa`, Google, GitHub and passkeys, BFF cookie session, CSRF header,
back-channel logout) moves from sprint 4 to sprint 2 as `docs/specs/006-sign-in-keycloak-bff.md`,
ported from Tabayyun's `tabayyun.auth`. Without orgs yet, access follows
`SAHIFA_ADMIN_EMAIL` and `SAHIFA_ALLOWED_EMAILS`; everyone else who signs in gets "No access
yet". Org → workspace → connection RBAC with row-level security stays in sprint 4.

`prod` now starts in one of two ways: `SAHIFA_AUTH_MODE=oidc` with the full OIDC settings, or
`SAHIFA_ACCESS_GATE=basic-auth-at-proxy` with `SAHIFA_AUTH_MODE=proxy` (every request acts as
one principal behind the proxy's password). An unset mode resolves to `proxy` when the gate is
declared, so staging keeps starting until it switches to `oidc`. `dev` stays refused in `prod`.
