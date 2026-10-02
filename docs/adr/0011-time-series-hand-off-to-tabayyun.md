# ADR-0011: Time-series columns are handed to Tabayyun's core

- **Status:** Proposed
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

Tables often hold measurements over time (meter reads, prices, sensor values). Tabayyun's Rust
core already runs 20+ time-series checks (gaps, staleness, flatlines, spikes, drift,
changepoints) with episode aggregation. Reimplementing them in SQL would be weaker and
duplicate work.

## Decision

When a profile shows a timestamp column plus at least one measure column and either a series
key column (low-cardinality attribute) or a single series, Sahifa offers a **time-series
assessment**: it extracts `(series key, ts, value)` from the sample ordered by time (bounded by
`SAHIFA_TS_MAX_ROWS`, default 2 M) and runs `tabayyun_core.run_checks` in-process through the
optional `sahifa-core[timeseries]` extra (the `tabayyun_core` wheel). Findings map to Sahifa's
accuracy and currentness dimensions with the check id kept (`tby.*`).

## Consequences

- Needs the `tabayyun_core` wheel published to a package index (owner task in Tabayyun).
- Scheduled for R2, sprint 6; until then the profile marks such assets "time series detected".
