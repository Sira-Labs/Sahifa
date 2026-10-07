# Check catalogue — the first 30

Thirty checks in six dimensions, plus store-health items that are reported but not scored.
**R1** checks ship in release 0.1; **R2** and **R3** checks need the profile history, the UI
for custom rules, or mining that is not built yet. Sources for the methods are in
`docs/research/03-research-methods.md`; the reference implementation we compared against is
DataKitchen TestGen (research 01).

Column roles used below are inferred per column (spec 002): **key** (declared primary key or
unique constraint, a column named `id`, or `<asset>_id` with ≥ 99 % distinct values),
**foreign_key** (declared, or `<name>_id` that is not a key), **timestamp** (date or
timestamp type), **measure** (other numbers), **description** (text with mean length > 50),
**attribute** (everything else).

## Overview

| # | Check | Dimension | Level | Kind | Severity | Evaluation | Release |
|---|---|---|---|---|---|---|---|
| 1 | `sah.not_null` | completeness | column | rule | critical for key and foreign_key, high for timestamp, low otherwise | sql | R1 |
| 2 | `sah.not_blank` | completeness | column | rule | medium | sql | R1 |
| 3 | `sah.row_count` | completeness | asset | rule | critical | sql | R1 |
| 4 | `sah.type_conformance` | validity | column | rule | medium | sql | R1 |
| 5 | `sah.semantic_format` | validity | column | rule | high | python | R1 |
| 6 | `sah.pattern` | validity | column | baseline | medium | sql | R1 |
| 7 | `sah.accepted_values` | validity | column | baseline | high | sql | R1 |
| 8 | `sah.length` | validity | column | baseline | low | sql | R1 |
| 9 | `sah.whitespace` | validity | column | rule | low | sql | R1 |
| 10 | `sah.non_printing` | validity | column | rule | medium | sql | R1 |
| 11 | `sah.code_list` | validity | column | manual | high | sql | R2 |
| 12 | `sah.range` | accuracy | column | baseline | high | sql | R1 |
| 13 | `sah.outliers` | accuracy | column | rule | low | sql | R1 |
| 14 | `sah.future_dates` | accuracy | column | rule | high | sql | R1 |
| 15 | `sah.implausible_dates` | accuracy | column | rule | medium | sql | R1 |
| 16 | `sah.distribution_shift` | accuracy | column | baseline | medium | history | R2 |
| 17 | `sah.metric_anomaly` | accuracy | column, asset | baseline | medium | history | R2 |
| 18 | `sah.foreign_key` | consistency | column | rule | critical | sql | R1 |
| 19 | `sah.column_order` | consistency | asset | rule | high | sql | R1 |
| 20 | `sah.casing_variants` | consistency | column | rule | low | python | R1 |
| 21 | `sah.mixed_types` | consistency | column | rule | medium | sql | R2 |
| 22 | `sah.functional_dependency` | consistency | asset | baseline | medium | sql | R3 |
| 23 | `sah.aggregate_balance` | consistency | asset | manual | high | sql | R2 |
| 24 | `sah.schema_drift` | consistency | asset | baseline | high | history | R2 |
| 25 | `sah.unique` | uniqueness | column | rule | critical | sql | R1 |
| 26 | `sah.duplicate_rows` | uniqueness | asset | rule | high | sql | R1 |
| 27 | `sah.near_duplicates` | uniqueness | column | rule | medium | python | R2 (normalised), R3 (Splink) |
| 28 | `sah.freshness` | currentness | asset | baseline | high | sql | R1 |
| 29 | `sah.volume_trend` | currentness | asset | baseline | high | history | R2 |
| 30 | `sah.custom_sql` | any | asset | manual | as set | sql | R2 |

R1 ships 20 checks (1–10, 12–15, 18–20, 25, 26, 28).

## Completeness

### 1. `sah.not_null` — Missing values

- **Applies to:** every column.
- **Fails:** `column IS NULL`.
- **Parameters:** `max_fail_ratio`: 0 for key, foreign_key and timestamp roles and for columns
  declared `NOT NULL`; 1.0 otherwise, which means the column's null share lowers the
  completeness score but raises no finding until the owner tightens it. Retiring the check
  marks a column as optional and removes it from the score.
- **Why this way:** a column that is 40 % empty is a completeness fact (ISO 25012 measures
  it this way) but often a legitimate optional field. Scoring it at low weight keeps the
  score honest without flooding the inbox.
- **Explain:** "{failed} of {evaluated} rows have no value in {column} ({fail_pct})."

### 2. `sah.not_blank` — Blank and placeholder values

- **Applies to:** text columns.
- **Fails:** the trimmed value is empty, or its lower-case form is one of `n/a`, `na`, `null`,
  `none`, `nil`, `-`, `--`, `?`, `unknown`, `undefined`, `#n/a`.
- **Parameters:** `max_fail_ratio` 0; `tokens` (the list above, editable).
- **Why:** placeholders hide missing values from `IS NULL` checks (TestGen's "non-standard
  blanks").
- **Explain:** "{failed} values in {column} are blank or a placeholder such as 'N/A'."

### 3. `sah.row_count` — Empty table

- **Applies to:** every asset. **Fails:** the asset has no rows.
- **Baseline (R2):** a row-count band from the history (`sah.volume_trend` covers growth).
- **Explain:** "{asset} has no rows."

## Validity

### 4. `sah.type_conformance` — Values of the wrong type

- **Applies to:** text columns where at least 90 % of non-null values look like numbers or at
  least 90 % look like dates (ISO `YYYY-MM-DD[ T]…`, `DD.MM.YYYY`, `DD/MM/YYYY`,
  `MM/DD/YYYY`). Columns whose numeric-looking values have leading zeros are codes, not
  numbers, and are skipped.
- **Fails:** a non-null value that does not look like the majority type.
- **Explain:** "{failed} values in {column} are not {expected_type}s, although {majority_pct}
  of the column is."

### 5. `sah.semantic_format` — Invalid email, IBAN, VAT ID, …

- **Applies to:** text columns whose semantic type was inferred (at least 80 % of sampled
  values pass one validator).
- **Validators (R1):** `email` (RFC 5322 simplified: one `@`, a dotted domain), `url`
  (`http(s)://host…`), `uuid` (8-4-4-4-12 hex), `iban` (ISO 13616: country, length per
  country, mod-97 = 1), `eu_vat` (the 27 EU formats plus `XI`; format only, no VIES lookup),
  `iso_country` (ISO 3166-1 alpha-2 and alpha-3), `iso_currency` (ISO 4217 alpha-3),
  `phone_e164` (`+` and 8–15 digits after removing spaces, dashes and brackets),
  `postcode_de` (five digits, `01001`–`99998`).
- **Fails:** a non-null value that does not pass the column's validator.
- **Evaluation:** Python over `(value, count)` groups (the checksum cannot be pushed down
  portably).
- **Explain:** "{failed} of {evaluated} values in {column} are not valid {semantic_label}s."

### 6. `sah.pattern` — Value shape changed (baseline)

- **Applies to:** text columns whose top three pattern classes (`A` for letters, `9` for
  digits, punctuation kept) cover at least 99 % of non-null values, with at least 50 values.
- **Fails:** a value whose pattern class is not among them.
- **Explain:** "{failed} values in {column} do not have the usual shape ({patterns})."

### 7. `sah.accepted_values` — Unexpected category (baseline)

- **Applies to:** columns with 2–20 distinct values, at least 50 non-null values and a
  distinct ratio at or below 20 %.
- **Fails:** a value outside the observed set.
- **Explain:** "{failed} rows in {column} have a value outside {values}."

### 8. `sah.length` — Text too short or too long (baseline)

- **Applies to:** text columns with at least 50 values. **Parameters:** observed min and max
  length. **Fails:** a value outside them.

### 9. `sah.whitespace` — Leading or trailing spaces

- **Applies to:** text columns. **Fails:** `value <> trim(value)`.
- **Why:** breaks joins and equality filters silently.

### 10. `sah.non_printing` — Control and invisible characters

- **Applies to:** text columns. **Fails:** the value contains a control character (U+0001–
  U+0008, U+000B, U+000C, U+000E–U+001F, U+007F), a no-break space (U+00A0), a zero-width
  space (U+200B) or a byte-order mark (U+FEFF).

### 11. `sah.code_list` — Value in a reference list (R2)

A manual check against a list the owner uploads or a built-in code list (ISO 3166-2
subdivisions, NUTS regions, ICD-10).

## Accuracy

### 12. `sah.range` — Outside the observed range (baseline)

- **Applies to:** numeric, date and timestamp columns with at least 50 values.
- **Parameters:** `min`, `max` as observed. **Fails:** a value outside them.
- **R2:** the bounds come from the history with a chosen false-alarm rate.

### 13. `sah.outliers` — Extreme values

- **Applies to:** numeric columns (role measure) with at least 30 values and a non-zero MAD.
- **Fails:** `|x − median| / (1.4826 · MAD) > 6`.
- **Parameters:** `max_fail_ratio` 0.01 (heavy tails are normal for amounts).

### 14. `sah.future_dates` — Dates in the future

- **Applies to:** date and timestamp columns, except names containing `due`, `expir`,
  `valid_to`, `valid_until`, `end`, `until`, `planned`, `scheduled`, `deadline`, `forecast`.
- **Fails:** value later than scan time plus one day.

### 15. `sah.implausible_dates` — Dates before 1900 or after 2200

- **Applies to:** date and timestamp columns.
- **Fails:** value before 1900-01-01 or after 2200-01-01 (catches 0001-01-01 and
  9999-12-31 sentinels).

### 16. `sah.distribution_shift` (R2)

Numeric: Wasserstein distance and KS on the sample against the previous scan, thresholds on
effect size, not p-values (large tables make every test significant). Categorical: Jensen–
Shannon divergence and PSI with critical values instead of the 0.1/0.25 rule of thumb.

### 17. `sah.metric_anomaly` (R2)

Null share, distinct count, mean and row count per scan as metric history; STL baseline and
conformal thresholds give an alert threshold with a chosen false-alarm rate
(Auto-Validate-by-History).

## Consistency

### 18. `sah.foreign_key` — Orphan references

- **Applies to:** declared foreign keys, and inferred ones: a column `<name>_id` where the
  scan contains an asset named `<name>`, `<name>s` or `<name>es` with a unique key column
  `id` or `<name>_id`, and at least 90 % of the sampled values are found there.
- **Fails:** a non-null value not found in the parent's key column (the full parent, not its
  sample).
- **Explain:** "{failed} rows in {asset}.{column} refer to {parent} rows that do not exist."

### 19. `sah.column_order` — Start after end

- **Applies to:** pairs of date, timestamp or numeric columns in one asset named
  `X_start`/`X_end`, `start_X`/`end_X`, `X_from`/`X_to`, `valid_from`/`valid_to`,
  `created_at`/`updated_at`, `min_X`/`max_X`.
- **Fails:** both values present and the first is greater than the second.

### 20. `sah.casing_variants` — Same value, different spelling

- **Applies to:** text columns with 2–10,000 distinct values.
- **Fails:** a row whose value has the same lower-case, trimmed form as a more frequent
  different value (`Berlin`, `berlin `, `BERLIN`).
- **Evaluation:** Python over `(value, count)` groups.

### 21–24 (R2/R3)

`sah.mixed_types` (a text column with a mix of numbers and words between 30 % and 90 %),
`sah.functional_dependency` (approximate dependencies mined with a HyFD-style algorithm,
always proposed and ranked, because mined constraints are mostly false: research 03),
`sah.aggregate_balance` (a child sum equals a parent total), `sah.schema_drift` (columns
added, removed or retyped since the last scan).

## Uniqueness

### 25. `sah.unique` — Duplicate keys

- **Applies to:** key-role columns and declared unique constraints.
- **Fails:** rows beyond the first occurrence of each value, `count(col) − count(distinct
  col)` on the sample.

### 26. `sah.duplicate_rows` — Identical rows

- **Applies to:** every asset with at least two scalar columns. JSON and binary columns are
  left out of the comparison.
- **Fails:** rows beyond the first occurrence of an identical row.

### 27. `sah.near_duplicates` (R2, R3)

R2: duplicates after normalising case, whitespace and punctuation in name-like columns. R3:
probabilistic entity resolution with Splink (Fellegi–Sunter, unsupervised) on DuckDB.

## Currentness

### 28. `sah.freshness` — Data not updated (baseline)

- **Applies to:** assets with a timestamp-role column named `*_at`, `*_time`, `*_date`,
  `ts`, `timestamp`, `loaded_at`, `updated` or `created`; the newest such column is used.
- **Parameters:** `max_age`: twice the current age of the newest value, at least one day,
  rounded up to whole hours. **Fails:** newest value older than `max_age` at scan time.
- **R2:** `max_age` from the observed arrival cadence (`sah.volume_trend`).

### 29. `sah.volume_trend` (R2)

Rows per day from the timestamp column against a seasonal baseline; late or missing loads.

### 30. `sah.custom_sql` (R2)

A fail predicate or a query returning failing rows, written by the owner, with the same
result shape.

## SAP pack (R2, ADR-0014)

Generated when a profile looks like SAP data (a `MANDT` column, `DATS` or `NUMC` patterns, or
an SAP connector). Same manifest, result and scoring as the generic checks.

| Check | Dimension | What it catches |
|---|---|---|
| `sap.dats_valid` | validity | `CHAR(8)` dates that are not valid `YYYYMMDD`; `00000000` counts as missing, not invalid |
| `sap.alpha_conversion` | consistency | keys (`MATNR`, `KUNNR`, `LIFNR`) zero-padded in some rows and not in others |
| `sap.currency_reference` | consistency | non-zero amounts without a currency key, or with an unknown one (`TCURC`) |
| `sap.unit_reference` | consistency | non-zero quantities without a unit of measure (`T006`) |
| `sap.client_consistency` | consistency | rows or references crossing clients (`MANDT`) |
| `sap.deletion_flag_share` | store health | share of rows flagged for deletion (`LOEKZ`, `LOEVM`) |

## Store health (reported, not scored)

| Item | What it reports | Release |
|---|---|---|
| `store.empty_table` | assets with no rows | R1 |
| `store.no_primary_key` | Postgres tables without a declared primary key | R1 |
| `store.numbers_as_text` | text columns whose every value is a number without leading zeros | R1 |
| `store.unused_table` | tables nobody queried for 90 days (query logs, `pg_stat_user_tables`) | R3 |
| `store.duplicate_tables` | tables whose contents overlap (MinHash, LSH Ensemble) | R3 |
| `store.small_files` | Iceberg and Delta partitions with more than four data files | R3 |
| `store.missing_index` | Postgres foreign keys without an index, Dexter and HypoPG advice | R3 |

## Accuracy benchmark (release 0.1)

How well each R1 check finds faults that are known to be in the data, and how often it flags
data nobody broke (spec 014). Measured on 2026-10-07 at commit `7ead9e9`, pinned to 2 CPUs, in
2 min 49 s:

```
sahifa bench-accuracy --seeds 20 --rows 5000 --sample-rows 500
```

**How it is measured.** The benchmark uses the synthetic shop and its fault list, which is
counted from the final rows. For each of 20 seeds it runs five scans:
- the faulty shop;
- its clean twin;
- the drift twin, against the baselines the clean twin proposed, locked;
- a clean shop of another seed, against the same locked baselines;
- the faulty shop again, sampled at 500 rows.

The measures are counts per check, asset and column, whether or not a finding is raised. A
fault group is one seed × asset × column. "Unexpected" counts checks that flagged rows where no
fault was put in. Interval coverage is the share of fault groups on sampled assets where the
95 % interval holds the full-read pass ratio.

| Check | Kind | Fault groups (rows) | Detected | Count exact | Unexpected | Clean twin: findings, failing rows | Locked baseline on new data: findings | Sampled: detected | Sampled: interval coverage |
|---|---|---|---|---|---|---|---|---|---|
| `sah.not_null` | rule | 40 (480) | 100 % | 100 % | 0 | 0, 0 of 1,572,000 | – | 82 % | 92 % |
| `sah.not_blank` | rule | 20 (100) | 100 % | 100 % | 0 | 0, 0 of 358,000 | – | 90 % | 85 % |
| `sah.row_count` | rule | 20 (20) | 100 % | 100 % | 0 | 0, 0 of 100 | – | 100 % | – |
| `sah.type_conformance` | rule | 20 (120) | 100 % | 100 % | 0 | 0, 0 of 0 | – | 70 % | 100 % |
| `sah.semantic_format` | rule | 60 (378) | 100 % | 100 % | 0 | 0, 0 of 162,000 | – | 77 % | 90 % |
| `sah.pattern` | baseline | 20 (100) | 100 % | 100 % | 0 | – | 0 of 120 | – | – |
| `sah.accepted_values` | baseline | 20 (400) | 100 % | 100 % | 0 | – | 0 of 120 | – | – |
| `sah.length` | baseline | 20 (100) | 100 % | 100 % | 0 | – | 9 of 260 | – | – |
| `sah.whitespace` | rule | 20 (157) | 100 % | 100 % | 0 | 0, 0 of 358,000 | – | 100 % | 95 % |
| `sah.non_printing` | rule | 20 (60) | 100 % | 100 % | 0 | 0, 0 of 358,000 | – | 90 % | 100 % |
| `sah.range` | baseline | 40 (50,200) | 100 % | 100 % | 0 | – | 122 of 200 | – | – |
| `sah.outliers` | rule | 20 (2,000) | 100 % | 100 % | 0 | 0, 0 of 332,000 | – | 100 % | 90 % |
| `sah.future_dates` | rule | 20 (20) | 100 % | 100 % | 0 | 0, 0 of 350,000 | – | 65 % | 100 % |
| `sah.implausible_dates` | rule | 20 (20) | 100 % | 100 % | 0 | 0, 0 of 350,000 | – | 50 % | 100 % |
| `sah.foreign_key` | rule | 40 (602) | 100 % | 100 % | 0 | 0, 0 of 280,000 | – | 70 % | 100 % |
| `sah.column_order` | rule | 20 (300) | 100 % | 100 % | 0 | 0, 0 of 100,000 | – | 70 % | 95 % |
| `sah.casing_variants` | rule | 20 (397) | 100 % | 100 % | 0 | 0, 0 of 216,000 | – | 100 % | 100 % |
| `sah.unique` | rule | 20 (320) | 100 % | 100 % | 0 | 0, 0 of 252,000 | – | 20 % | 100 % |
| `sah.duplicate_rows` | rule | 20 (195) | 100 % | 100 % | 0 | 0, 0 of 252,000 | – | 15 % | 100 % |
| `sah.freshness` | baseline | 20 (20) | 100 % | 100 % | 0 | – | 0 of 80 | – | – |

**Reading the table.**

- **Full read.**
  - Every R1 check finds every fault it was given, with the exact number of rows, and flags
    nothing else.
  - The clean twin has no findings and not one failing row.
  - `type_conformance` evaluates no rows on the clean twin: there, `invoices.total` is a
    number column, and the check applies only to text that should be numbers.
- **Locked baselines on legitimate new data.**
  - A locked `range` baseline is the minimum and maximum of one scan. On a clean shop with
    other random values, it raises a finding in 122 of 200 cases. This happens in 7 to 9 of 10
    runs for continuous columns (amounts, prices, payload sizes, timestamps) and never for
    `orders.quantity` (1–4). For timestamps it also means every new load past the locked
    maximum raises a finding.
  - `length` fires 9 times in 260, all on `customers.email`, whose longest address varies
    by seed.
  - Until baselines are learnt from several scans (R2, sprint 5), lock a `range` baseline
    only on columns with fixed limits.
- **Sampled scans.** These are rows read, not tables chosen; each shop has 5,000 orders and
  1,000 customers.
  - A fault in only a few rows is often outside a 500-row sample: one future date among
    1,000 customers is found in 65 % of seeds, one default date in 50 %.
  - `unique` and `duplicate_rows` need both copies of a row in the sample, so they rarely see
    duplicates there (20 % and 15 %). Their intervals still hold the full-read share.
- **Interval coverage.**
  - Coverage is 85–100 % against the nominal 95 %, over 20 groups per check.
  - `not_blank`, at 85 % (17 of 20), is below the 90 % this spec asks for. Its five
    placeholders sit among 1,000 customers, half of whom are in the sample. The Wilson
    interval with the finite-population correction may be too narrow for such rare faults;
    see `TASKS.md`.

## Suggested next step per check

Each finding carries one plain sentence of advice, from this table:

| Check | Suggested next step |
|---|---|
| not_null | Find the load that leaves the column empty, or retire the check if the column is optional. |
| not_blank | Convert placeholders to NULL in the pipeline; decide whether the column is optional. |
| row_count | Check the last load of the table. |
| type_conformance | Cast the column in the pipeline and route rows that fail the cast to a reject table. |
| semantic_format | Validate at entry; for IBAN and VAT IDs, check the source system's input mask. |
| pattern, length, accepted_values, range | If the new values are legitimate, approve the new baseline; otherwise trace the source. |
| whitespace, non_printing | Trim and clean in the pipeline; check the export's encoding. |
| outliers | Look at the example values; a unit or decimal-separator error often shows as a factor of 100 or 1,000. |
| future_dates, implausible_dates | Check time zones and default dates in the source application. |
| foreign_key | Load parents before children, or find where the parent rows were deleted. |
| column_order | Check whether the two columns are swapped in the load. |
| casing_variants | Normalise case in the pipeline or map variants to one code. |
| unique, duplicate_rows | Find the double load; add a unique constraint where the store allows it. |
| freshness | Check the scheduler of the load that writes this table. |
