# ADR-0004: Scores per ISO 25012 dimension with 95 % intervals

- **Status:** Accepted
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

Every tool we surveyed reports quality scores as point values (research 02, gap 1), and none
follows ISO/IEC 25012/25024. A score computed on a 1 % sample looks as certain as one computed
on every row. Heinrich et al. set five requirements for data-quality metrics (bounded range,
interval scale, reliable parameters, sound aggregation, cost-efficiency). TestGen's scoring
(prevalence × risk factor, weighted by table and column importance) is a good model for
weights but not for uncertainty (research 01).

## Decision

- Six reported dimensions, each mapped to an ISO/IEC 25012 characteristic: completeness,
  validity, accuracy, consistency, uniqueness, currentness (domain model).
- Each check yields a pass ratio `p = (n − k)/n` with a **95 % Wilson interval** and the
  **finite-population correction** for sampled scans; a full read has zero sampling width.
- A column's dimension score is the **weighted geometric product** of its check ratios
  (weights by severity); its interval comes from the **delta method** on the log.
- Asset and store scores are **weighted means** (column roles, table size `1 + log10(1 +
  rows)`), with variance propagated under independence; overall is the mean of dimensions.
- Only `active` and `locked` checks count (ADR-0005). Every weight and threshold is shown in
  the report.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Point scores (TestGen, Soda) | Simple | Hides sampling uncertainty | Our main differentiator is the interval |
| Bootstrap intervals | Fewer assumptions | Needs row-level resampling in the source, costly | Delta method is closed-form and cheap |
| Bayesian hierarchical model | Shrinks noisy small tables | Opaque to users, slower | Possible R3 option for very small tables |
| Sum of penalties (100 − Σ) | Familiar | Unbounded below, not an interval scale | Fails Heinrich's requirements |

## Consequences

- The independence assumption overstates certainty when failures correlate (one bad load
  breaks several checks); the report says the interval covers sampling uncertainty only.
- Checks with `n = 1` (asset level) have no interval; they move the score in steps.
- R2 adds conformal thresholds with a chosen false-alarm rate for history-based checks; the
  score model stays the same.
