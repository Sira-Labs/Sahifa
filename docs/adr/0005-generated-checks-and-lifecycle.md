# ADR-0005: Generated checks with a lifecycle; Sahifa never writes to sources

- **Status:** Accepted
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

Hand-written tests cap coverage (the Great Expectations model); TestGen generates tests from
the profile and lets users lock them (research 01). Automatically mined constraints are mostly
false: for denial constraints more than 95 % of discovered rules are wrong, and automatic
repair is unreliable outside lab conditions (research 03). LLM agents are worse than a
profiling baseline at detection but good at proposing rules.

## Decision

- Checks are **generated** from the profile in two kinds: **rules** (product opinions that hold
  for any data: a key is unique, an IBAN passes mod-97) start `active`; **baselines** (learned
  from this data: the observed range, value set, pattern) start `proposed`.
- Lifecycle: `proposed → active → locked`, any state `→ retired`, `retired → active`.
  Only `active` and `locked` checks score and raise findings; `proposed` checks are evaluated
  and shown so the owner can judge them.
- Regeneration updates `active` generated checks, never `locked`, `manual` or `retired` ones.
- Suggestions from mining (R3) or an LLM (R3) always start `proposed`, with their evidence.
- **Sahifa never writes to a source.** Proposed fixes are SQL or dbt snippets on a finding.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| All generated checks active | Maximum coverage at once | Baselines pass by construction on the first scan, mined rules are noisy | Inflated scores and alert fatigue |
| Only manual checks | No false positives from generation | Coverage stays tiny | The product's point is coverage |
| Automatic repair | Less work for the owner | Unreliable; writing needs write credentials | Read-only is a principle |

## Consequences

- R1 sprint 1 regenerates checks per scan inside the report; spec 007 persists them per asset.
- The UI needs approve, lock and retire actions with an audit trail (R2 audit log).
