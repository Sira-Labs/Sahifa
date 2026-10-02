# ADR-0008: Apache-2.0 licence; Apache/MIT-only engines

- **Status:** Accepted
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

The landscape moved toward restrictive licences: Soda Core to Elastic License 2.0, the
OpenMetadata profiler and UI to the Collate Community License, the original dbt Fusion under
ELv2; cleanlab, Zingg and Desbordante are AGPL (research 02 and 03). TestGen is Apache-2.0
but gates multi-user use in its edition, not its licence.

## Decision

- Sahifa is **Apache-2.0**, with a `NOTICE` file; contributions under the same licence.
- **Runtime dependencies of the core, API and web must be under a permissive licence** (MIT,
  BSD, Apache-2.0, ISC, PSF, MPL-2.0 for unmodified files). AGPL, GPL, SSPL, ELv2, BSL and
  "community" licences that forbid hosting are not allowed in the shipped images.
- An optional plugin may use another licence only as a separate package the user installs.
- CI checks licences of Python and npm dependencies (R1 sprint 3, `pip-licenses`,
  `license-checker`).
- No edition gating: every feature is in the open-source build.

## Consequences

- Splink (MIT) for entity resolution; HyFD-style mining reimplemented rather than linking
  Desbordante (AGPL); cleanlab only as an optional plugin.
