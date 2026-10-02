# ADR-0013: Open Data Contract Standard v3 as the contract format

- **Status:** Accepted (implementation R2)
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

ODCS (Bitol, LF AI & Data, Apache-2.0) is becoming the shared format for data contracts; v3.2
carries quality rules as text, library metrics, SQL or engine-specific blocks, with a
dimension field, and datacontract-cli (MIT) tests ODCS contracts on many engines (research 02).
TestGen's contract support is "in development".

## Decision

A contract per asset is **inferred** from the profile and the active and locked checks: schema
(names, logical types, required, unique, primary key), quality rules (each Sahifa check as an
ODCS `library` or `sql` rule with its dimension), freshness and volume SLAs. It is exported as
ODCS v3 YAML, and an imported ODCS contract creates `manual` checks. Sahifa's checks stay the
source of truth; the contract is a view of them.

## Consequences

Spec 011 (R2) defines the mapping table; the check manifest keeps an `odcs` field from the start.
