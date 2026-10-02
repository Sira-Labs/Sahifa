# ADR-0001: Python core; checks run as SQL where the data lives

- **Status:** Accepted
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

Sahifa assesses tables in stores it does not own: Postgres, warehouses, lakehouse tables and
files. Copying a table out to check it costs egress, time and a second copy of personal data.
TestGen shows that checks pushed down as SQL scale to whole warehouses (research 01). Tabayyun
has a Rust core because its work is CPU-bound arithmetic on series already in memory; Sahifa's
work is mostly a few aggregate queries per table, so the time is spent in the source engine,
not in our process.

## Decision

- The core is a **Python library** (`sahifa_core`, Python 3.11+), shipped inside the API image
  and as a CLI.
- **Row-level checks are SQL fail predicates evaluated in the source** in one aggregate query
  per asset (`SUM(CASE WHEN <predicate> THEN 1 ELSE 0 END)` per check). Profiling is one
  aggregate query per asset plus grouped queries for top values and patterns.
- A small **dialect layer** (`sql.py`) renders the few functions that differ between engines
  (regex match and replace, length, trim, sampling, current time). Identifiers are quoted and
  literals rendered with **SQLGlot** (MIT) for the target dialect; values from the data are
  never concatenated into SQL text.
- Checks that need logic SQL cannot express portably (IBAN mod-97, casing variants) run in
  Python on `(value, count)` groups fetched from the sample, at most 50,000 groups per column.
- Time-series work is not reimplemented: it is handed to Tabayyun's Rust core (ADR-0011).

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Rust core like Tabayyun | Fast on in-memory data | The data is not in memory; the time is in the source | Wrong bottleneck |
| Pull rows into Arrow/Polars and check locally | One implementation of every check | Egress, memory, a copy of personal data | Fails at warehouse scale |
| Great Expectations Core as the engine | Large expectation library | No profiling-driven generation, heavy runtime, its own result model | We would wrap more than we use; usable as an export target later |
| Ibis for every query | Portable expression API | Another abstraction for a handful of functions; regex and sampling still differ | Revisit if the dialect layer grows past ~10 functions |

## Consequences

- Each new engine needs a dialect class and a connector; the checks stay unchanged.
- Integration tests must run against each engine (DuckDB in-process, Postgres in CI).
- Sampling semantics differ per engine; the report records how the sample was drawn.
