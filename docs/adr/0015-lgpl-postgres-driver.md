# ADR-0015: LGPL-3.0 allowed for the Postgres driver (psycopg), used unmodified

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** owner
- **Amends:** ADR-0008

## Context

ADR-0008 allows only permissive licences (MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0) for the
runtime dependencies of core, API and web. The licence audit of spec 012 found that the
Postgres driver, `psycopg` 3 with `psycopg-binary` and `psycopg-pool`, is LGPL-3.0. It is used
by:
- the core's Postgres connector (read-only source sessions, ADR-0006);
- the API's SQLAlchemy engine;
- Procrastinate, the job queue of ADR-0009, which supports only psycopg 3.

LGPL-3.0 is not one of the licences ADR-0008 forbids (AGPL, GPL, SSPL, ELv2, BSL, "community"
licences), but it is not on its allowlist either. The LGPL lets a program under another licence
use the library unmodified, as long as:
- the library's licence ships with it;
- the user can replace the library with another version.

In a Python install both hold: the wheel carries its licence in its `dist-info`, and the
package can be swapped with `pip`.

## Decision

- LGPL-3.0 is allowed for **psycopg, psycopg-binary and psycopg-pool only**, used unmodified
  as installed packages. Sahifa never vendors, patches or statically links them.
- The licence check of spec 012 lists these three packages as named exceptions, with this ADR
  as the reason. Any other LGPL dependency fails CI until a new ADR allows it.
- The images keep the packages' licence files (their `dist-info`). `NOTICE` names psycopg and
  its licence.
- Everything else in ADR-0008 stands.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Replace psycopg with asyncpg (Apache-2.0) or pg8000 (BSD) | Fully permissive | Procrastinate needs psycopg 3, so the job queue changes too; the core's sync connector would need a rewrite; pg8000 is much slower | Large rework for a licence that already permits our use |
| Keep psycopg as an unrecorded exception | No new document | Deviates from ADR-0008 silently, against CLAUDE.md | Decisions are recorded |

## Consequences

- The licence job has exactly three named LGPL exceptions, each pointing here.
- A future switch of the job queue or the driver can drop this exception.
- Distributors of Sahifa images must keep the licence files, which the images already do.
