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
