# Performance

**Budget** (`03-system-architecture.md`, spec 013): a 1,000-table Postgres schema, sampled at
100,000 rows per table, scans in under 10 minutes on 2 vCPU.

**Result:** it scans in **8 min 13 s** with two worker sessions.

## How it is measured

1. **Create the schema:** `sahifa bench-schema <url> --schema wide` with the default mix.
   - 1,000 tables of ten columns: 700 of 10,000 rows, 270 of 100,000 rows and 30 of 1 million
     rows.
   - A parent table `customers` of 100,000 rows, referenced by every table through a declared
     (`NOT VALID`) foreign key.
   - 64 million rows, 9.6 GB.
2. **Pin to 2 CPUs.** Postgres and the scan both run on 2 CPUs: `taskset -pc 0,1` on every
   Postgres process, and `taskset -c 0,1` for the scan.
3. **Scan:** `sahifa scan '<url>?schemas=wide' --workers N --out report.json`.
4. **Break down:** the report's `stats` and each asset's `duration_s` and `queries`.

**Machine:**
- Intel Xeon at 2.10 GHz, 4 vCPU of which 2 are used, 15 GB of memory.
- Postgres 16.14 with default settings (`shared_buffers` 128 MB, `work_mem` 4 MB).
- Postgres and the scan on the same host.

## Results (2026-10-03)

| Run | Wall time | Queries | Per asset (max / mean) |
|---|---|---|---|
| Before spec 013 | Did not finish; about 3 days extrapolated | — | — |
| Spec 013, `--workers 1` | **15 min 47 s** (935 s scan) | 14,740 | 15 / 14.7 |
| Spec 013, `--workers 2` (default) | **8 min 13 s** (481 s scan) | 14,740 | 15 / 14.7 |

**Why the run before spec 013 did not finish.** The foreign-key check compared
`CAST(parent.id AS TEXT) = CAST(child.col AS TEXT)` inside the batched aggregate, so it ran once
per sampled row and could not use the parent's index.
- Measured: 30.6 s for 20,000 rows against a parent of 20,000 rows.
- Extrapolated to this schema: about 77 s per 10,000-row table and about 13 min per table of
  100,000 rows or more, which adds up to roughly 3 days.
- A scan of 50 tables of 20,000 rows did not finish in 10 minutes.

**Per tier, with two workers** (seconds summed over tables; the two workers overlap):

| Tier | Tables | s per table | Queries per table |
|---|---|---|---|
| 10,000 rows (read in full) | 700 | 0.32 | 15 |
| 100,000 rows (read in full) | 270 | 2.39 | 14 |
| 1,000,000 rows (sampled to 100,000) | 30 | 2.97 | 15 |
| Parent, 100,000 rows | 1 | 0.85 | 9 |

**Observations:**
- **Database time dominates** (93 % in a profiled run): the profile aggregate, the top values
  and the check aggregate each read the sample once. A 100,000-row table therefore costs about
  1 s per pass of reading.
- **Two workers halve the wall time.** The time per table barely changes (2.36 s against
  2.39 s for 100,000 rows), so the two sessions do not contend on 2 vCPU.
- **Sampling large tables:** a 1-million-row table sampled with `BERNOULLI` costs 25 % more
  than a 100,000-row table read in full, because every pass re-reads the table to draw the
  same sample.
- **Same findings.** Both runs give the same findings. The reports differ only in values
  measured against the scan's start time, which was 15 minutes apart between the runs: the
  age of the newest row, and dates counted as "in the future".

## Query budget per asset

At most:
- 9 fixed queries: 3 metadata, 1 row count, 3 profile, 1 check aggregate and 1 newest
  timestamp;
- plus 1 per foreign-key check;
- plus 1 per column with Python-evaluated checks;
- plus 1 per failing SQL check, at most 10 per asset.

`core/tests/test_performance.py` asserts this on the synthetic shop.

## Not done, and why

- **Guards in front of the profile's regexes:** they would save about 3 % of a 100,000-row
  table's time, and a guard could differ from Postgres's `\s` (spec 013, behaviour 3).
- **Drawing the sample once into DuckDB:** the largest remaining lever, since most passes
  re-read the sample. It conflicts with pushdown (ADR-0001); revisit with an ADR if a larger
  budget is needed.
