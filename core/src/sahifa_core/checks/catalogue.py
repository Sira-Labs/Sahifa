"""The 20 R1 checks of docs/checks/catalogue.md."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .. import semantics
from ..models import CheckSpec, ColumnProfile, Dimension, LogicalType, Role, Severity
from ..profile import pattern_regex
from ..sql import DATE_LIKE, LEADING_ZERO_NUMBER, NON_PRINTING_CLASS, NUMERIC_LIKE
from .base import Check, Context, pct, where

KEYISH = (Role.KEY, Role.FOREIGN_KEY)
FUTURE_OK = (
    "due",
    "expir",
    "valid_to",
    "valid_until",
    "end",
    "until",
    "planned",
    "scheduled",
    "deadline",
    "forecast",
)
MAX_GROUPS = 50_000


def _is_text(c: ColumnProfile) -> bool:
    return c.logical_type == LogicalType.TEXT


def _iso_dt(v: float | str | None) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


# --- completeness ---------------------------------------------------------------------------


class NotNull(Check):
    type = "sah.not_null"
    title = "Missing values"
    dimension = Dimension.COMPLETENESS
    next_step = "Find the load that leaves the column empty, or retire the check if the column is optional."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return True

    def severity_for(self, col: ColumnProfile | None) -> Severity:
        if col and col.role in KEYISH:
            return Severity.CRITICAL
        if col and col.role == Role.TIMESTAMP:
            return Severity.HIGH
        return Severity.LOW

    def tolerance_for(self, col: ColumnProfile | None) -> float:
        if col and (col.role in (*KEYISH, Role.TIMESTAMP) or col.declared_not_null):
            return 0.0
        return 1.0

    def domain(self, spec: CheckSpec, ctx: Context) -> str:
        return "TRUE"

    def n_expr(self, spec: CheckSpec, ctx: Context) -> str:
        return "count(*)"

    def k_expr(self, spec: CheckSpec, ctx: Context) -> str:
        return f"count(*) - count({ctx.q(spec.column or '')})"

    def examples_sql(self, spec: CheckSpec, ctx: Context) -> str | None:
        return None

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} of {n:,} rows have no value in {where(spec)} ({pct(k, n)})."


class NotBlank(Check):
    type = "sah.not_blank"
    title = "Blank and placeholder values"
    dimension = Dimension.COMPLETENESS
    next_step = "Convert placeholders to NULL in the pipeline; decide whether the column is optional."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return _is_text(col) and col.non_null > 0

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        return ctx.d.is_blank(ctx.d.as_text(ctx.q(spec.column or "")))

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} values in {where(spec)} are blank or a placeholder such as 'N/A' ({pct(k, n)})."


class RowCount(Check):
    type = "sah.row_count"
    title = "Empty table"
    dimension = Dimension.COMPLETENESS
    level = "asset"
    severity = Severity.CRITICAL
    evaluation = "profile"
    next_step = "Check the last load of the table."

    def generate(self, ctx: Context) -> list[CheckSpec]:
        return [self.spec(ctx)]

    def evaluate_profile(self, spec: CheckSpec, ctx: Context) -> tuple[int, int, list[tuple[str, int]]]:
        return 1, int(ctx.asset.population == 0), []

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{spec.asset.label} has no rows." if k else f"{spec.asset.label} has rows."


# --- validity -------------------------------------------------------------------------------


class TypeConformance(Check):
    type = "sah.type_conformance"
    title = "Values of the wrong type"
    dimension = Dimension.VALIDITY
    next_step = "Cast the column in the pipeline and route rows that fail the cast to a reject table."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        if not _is_text(col) or col.non_null < 10 or col.semantic_type:
            return False
        numeric = (col.numeric_like or 0) / col.non_null
        dates = (col.date_like or 0) / col.non_null
        return (numeric >= 0.9 and not col.leading_zero_numbers) or dates >= 0.9

    def params(self, col: ColumnProfile, ctx: Context) -> dict[str, Any]:
        numeric = (col.numeric_like or 0) >= (col.date_like or 0)
        majority = (col.numeric_like if numeric else col.date_like) or 0
        return {"expected": "number" if numeric else "date", "majority": round(majority / col.non_null, 4)}

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        pattern = NUMERIC_LIKE if spec.params["expected"] == "number" else DATE_LIKE
        return f"NOT {ctx.d.regex_full(ctx.d.as_text(ctx.q(spec.column or '')), pattern)}"

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        share = f"{spec.params['majority'] * 100:.1f} %"
        return (
            f"{k:,} values in {where(spec)} are not {spec.params['expected']}s, "
            f"although {share} of the column is."
        )


class SemanticFormat(Check):
    type = "sah.semantic_format"
    title = "Invalid format"
    dimension = Dimension.VALIDITY
    severity = Severity.HIGH
    evaluation = "python"
    next_step = "Validate at entry; for IBAN and VAT IDs, check the source system's input mask."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return _is_text(col) and col.semantic_type is not None

    def params(self, col: ColumnProfile, ctx: Context) -> dict[str, Any]:
        return {"semantic_type": col.semantic_type}

    def evaluate_values(
        self, spec: CheckSpec, values: list[tuple[str, int]]
    ) -> tuple[int, int, list[tuple[str, int]]]:
        validate = semantics.BY_NAME[spec.params["semantic_type"]].validate
        bad = [(v, c) for v, c in values if not validate(v.strip())]
        return sum(c for _, c in values), sum(c for _, c in bad), sorted(bad, key=lambda x: -x[1])[:5]

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        label = semantics.BY_NAME[spec.params["semantic_type"]].label
        plural = label + ("es" if label.endswith("s") else "s")
        return f"{k:,} of {n:,} values in {where(spec)} are not valid {plural} ({pct(k, n)})."


class Pattern(Check):
    type = "sah.pattern"
    title = "Unusual value shape"
    dimension = Dimension.VALIDITY
    kind = "baseline"
    next_step = "If the new values are legitimate, approve the new baseline; otherwise trace the source."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        if not _is_text(col) or col.non_null < 50 or not col.patterns or col.semantic_type:
            return False
        covered = sum(p.count for p in col.patterns[:3])
        return covered >= 0.99 * col.non_null and len(col.patterns) > 0

    def params(self, col: ColumnProfile, ctx: Context) -> dict[str, Any]:
        return {"patterns": [p.value for p in col.patterns[:3] if p.value]}

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        t = ctx.d.as_text(ctx.q(spec.column or ""))
        ors = " OR ".join(
            ctx.d.regex_full(t, pattern_regex(p, ctx.d.letter_class)) for p in spec.params["patterns"]
        )
        return f"NOT ({ors})"

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        shapes = ", ".join(spec.params["patterns"])
        return f"{k:,} values in {where(spec)} do not have the usual shape ({shapes})."


class AcceptedValues(Check):
    type = "sah.accepted_values"
    title = "Unexpected category"
    dimension = Dimension.VALIDITY
    kind = "baseline"
    severity = Severity.HIGH
    next_step = "If the new values are legitimate, approve the new baseline; otherwise trace the source."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return (
            col.logical_type in (LogicalType.TEXT, LogicalType.INTEGER)
            and col.role not in KEYISH
            and 2 <= (col.distinct or 0) <= 20
            and col.non_null >= 50
            and col.distinct_ratio <= 0.2
            and col.semantic_type not in semantics.PERSONAL
            and not col.top_truncated
        )

    def params(self, col: ColumnProfile, ctx: Context) -> dict[str, Any]:
        return {"values": sorted(v.value for v in col.top if v.value is not None)}

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        return f"{ctx.d.as_text(ctx.q(spec.column or ''))} NOT IN {ctx.d.literal_list(spec.params['values'])}"

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        vals = ", ".join(spec.params["values"][:8]) + ("…" if len(spec.params["values"]) > 8 else "")
        return f"{k:,} rows in {where(spec)} have a value outside {{{vals}}}."


class Length(Check):
    type = "sah.length"
    title = "Text too short or too long"
    dimension = Dimension.VALIDITY
    kind = "baseline"
    severity = Severity.LOW
    next_step = "If the new values are legitimate, approve the new baseline; otherwise trace the source."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return _is_text(col) and col.non_null >= 50 and col.min_length is not None

    def params(self, col: ColumnProfile, ctx: Context) -> dict[str, Any]:
        return {"min": col.min_length, "max": col.max_length}

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        n = f"length({ctx.d.as_text(ctx.q(spec.column or ''))})"
        return f"({n} < {int(spec.params['min'])} OR {n} > {int(spec.params['max'])})"


class Whitespace(Check):
    type = "sah.whitespace"
    title = "Leading or trailing spaces"
    dimension = Dimension.VALIDITY
    severity = Severity.LOW
    next_step = "Trim in the pipeline; check the export's settings."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return _is_text(col) and col.non_null > 0

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        t = ctx.d.as_text(ctx.q(spec.column or ""))
        return f"{t} <> trim({t})"

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} values in {where(spec)} have leading or trailing spaces ({pct(k, n)})."


class NonPrinting(Check):
    type = "sah.non_printing"
    title = "Control and invisible characters"
    dimension = Dimension.VALIDITY
    next_step = "Clean in the pipeline; check the export's encoding."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return _is_text(col) and col.non_null > 0

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        return ctx.d.regex_search(ctx.d.as_text(ctx.q(spec.column or "")), NON_PRINTING_CLASS)

    def example_value(self, spec: CheckSpec, ctx: Context) -> str | None:
        return ctx.d.as_text(ctx.q(spec.column or ""))

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} values in {where(spec)} contain control or invisible characters ({pct(k, n)})."


# --- accuracy -------------------------------------------------------------------------------


class Range(Check):
    type = "sah.range"
    title = "Outside the observed range"
    dimension = Dimension.ACCURACY
    kind = "baseline"
    severity = Severity.HIGH
    next_step = "If the new values are legitimate, approve the new baseline; otherwise trace the source."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return (
            (col.logical_type.is_numeric or col.logical_type.is_temporal)
            and col.non_null >= 50
            and col.min is not None
            and col.role not in KEYISH
        )

    def params(self, col: ColumnProfile, ctx: Context) -> dict[str, Any]:
        return {"min": col.min, "max": col.max}

    def _lit(self, v: Any, ctx: Context) -> str:
        dt = _iso_dt(v)
        return ctx.d.timestamp(dt) if dt else ctx.d.literal(float(v))

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        q = ctx.q(spec.column or "")
        return f"({q} < {self._lit(spec.params['min'], ctx)} OR {q} > {self._lit(spec.params['max'], ctx)})"

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} values in {where(spec)} are outside {spec.params['min']} – {spec.params['max']}."


class Outliers(Check):
    type = "sah.outliers"
    title = "Extreme values"
    dimension = Dimension.ACCURACY
    severity = Severity.LOW
    next_step = (
        "Look at the example values; a unit or decimal-separator error often shows as a factor of "
        "100 or 1,000."
    )

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return (
            col.logical_type.is_numeric
            and col.role == Role.MEASURE
            and col.non_null >= 30
            and bool(col.mad)
            and col.quantiles is not None
            and "p50" in col.quantiles
        )

    def params(self, col: ColumnProfile, ctx: Context) -> dict[str, Any]:
        assert col.quantiles is not None and col.mad
        return {"median": col.quantiles["p50"], "mad": col.mad, "z": 6.0}

    def tolerance_for(self, col: ColumnProfile | None) -> float:
        return 0.01

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        x = ctx.d.as_double(ctx.q(spec.column or ""))
        scale = 1.4826 * float(spec.params["mad"])
        median = ctx.d.literal(float(spec.params["median"]))
        return f"abs({x} - {median}) > {ctx.d.literal(spec.params['z'] * scale)}"

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return (
            f"{k:,} values in {where(spec)} are more than 6 robust deviations from the median "
            f"{spec.params['median']:g} ({pct(k, n)})."
        )


class FutureDates(Check):
    type = "sah.future_dates"
    title = "Dates in the future"
    dimension = Dimension.ACCURACY
    severity = Severity.HIGH
    next_step = "Check time zones and default dates in the source application."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return col.logical_type.is_temporal and not any(h in col.name.lower() for h in FUTURE_OK)

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        from datetime import timedelta

        return f"{ctx.q(spec.column or '')} > {ctx.d.timestamp(ctx.scan_time + timedelta(days=1))}"

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} values in {where(spec)} lie more than a day in the future ({pct(k, n)})."


class ImplausibleDates(Check):
    type = "sah.implausible_dates"
    title = "Dates before 1900 or after 2200"
    dimension = Dimension.ACCURACY
    next_step = "Check time zones and default dates in the source application."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return col.logical_type.is_temporal

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        q = ctx.q(spec.column or "")
        return (
            f"({q} < {ctx.d.timestamp(datetime(1900, 1, 1))} OR "
            f"{q} > {ctx.d.timestamp(datetime(2200, 1, 1))})"
        )

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return (
            f"{k:,} values in {where(spec)} are before 1900 or after 2200, often default dates ({pct(k, n)})."
        )


# --- consistency ----------------------------------------------------------------------------


class ForeignKey(Check):
    type = "sah.foreign_key"
    title = "Orphan references"
    dimension = Dimension.CONSISTENCY
    severity = Severity.CRITICAL
    next_step = "Load parents before children, or find where the parent rows were deleted."

    def generate(self, ctx: Context) -> list[CheckSpec]:
        out = []
        declared = {fk.column: fk for fk in ctx.asset.foreign_keys}
        for col in ctx.asset.columns:
            if col.non_null == 0:
                continue
            fk = declared.get(col.name)
            if fk is not None and fk.parent.label in ctx.assets:
                out.append(
                    self.spec(
                        ctx,
                        column=col.name,
                        origin="declared",
                        params={
                            "parent": fk.parent.label,
                            "parent_column": fk.parent_column,
                            "inferred": False,
                        },
                    )
                )
                continue
            if col.role != Role.FOREIGN_KEY or not col.name.lower().endswith("_id"):
                continue
            stem = col.name.lower()[:-3]
            for label, parent in ctx.assets.items():
                if parent is ctx.asset or parent.error:
                    continue
                if parent.ref.name.lower() not in {stem, stem + "s", stem + "es", stem[:-1] + "ies"}:
                    continue
                key = next(
                    (
                        c
                        for c in parent.columns
                        if c.role == Role.KEY and c.name.lower() in {"id", f"{stem}_id"}
                    ),
                    None,
                )
                if key is not None:
                    out.append(
                        self.spec(
                            ctx,
                            column=col.name,
                            params={"parent": label, "parent_column": key.name, "inferred": True},
                        )
                    )
                    break
        return out

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        parent = ctx.assets[spec.params["parent"]]
        pk = f"p.{ctx.d.ident(spec.params['parent_column'])}"
        return (
            f"NOT EXISTS (SELECT 1 FROM {ctx.src.full_ref(parent.ref)} AS p "
            f"WHERE {ctx.d.as_text(pk)} = {ctx.d.as_text(ctx.q(spec.column or ''))})"
        )

    def accept(self, spec: CheckSpec, n: int, k: int) -> bool:
        # An inferred reference is kept only when most values are found: mined constraints are
        # mostly noise (research 03), a 90 % match is evidence the guess is right.
        return not spec.params.get("inferred") or (n > 0 and (n - k) / n >= 0.9)

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return (
            f"{k:,} rows in {where(spec)} refer to {spec.params['parent']} rows that do not exist "
            f"({pct(k, n)})."
        )


PAIRS = (("_start", "_end"), ("start_", "end_"), ("_from", "_to"), ("min_", "max_"))
NAMED_PAIRS = (
    ("valid_from", "valid_to"),
    ("created_at", "updated_at"),
    ("start_date", "end_date"),
    ("ordered_at", "shipped_at"),
    ("order_date", "ship_date"),
)


class ColumnOrder(Check):
    type = "sah.column_order"
    title = "Start after end"
    dimension = Dimension.CONSISTENCY
    level = "asset"
    severity = Severity.HIGH
    next_step = "Check whether the two columns are swapped in the load."

    def generate(self, ctx: Context) -> list[CheckSpec]:
        cols = {
            c.name.lower(): c
            for c in ctx.asset.columns
            if c.logical_type.is_temporal or c.logical_type.is_numeric
        }
        out, seen = [], set()
        candidates = list(NAMED_PAIRS)
        for name in cols:
            for a, b in PAIRS:
                if a.startswith("_") and name.endswith(a):
                    candidates.append((name, name[: -len(a)] + b))
                elif not a.startswith("_") and name.startswith(a):
                    candidates.append((name, b + name[len(a) :]))
        for a, b in candidates:
            if (
                a in cols
                and b in cols
                and (a, b) not in seen
                and cols[a].logical_type == cols[b].logical_type
            ):
                seen.add((a, b))
                out.append(self.spec(ctx, columns=[cols[a].name, cols[b].name]))
        return out

    def domain(self, spec: CheckSpec, ctx: Context) -> str:
        a, b = (ctx.q(c) for c in spec.columns)
        return f"{a} IS NOT NULL AND {b} IS NOT NULL"

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        a, b = (ctx.q(c) for c in spec.columns)
        return f"{a} > {b}"

    def example_value(self, spec: CheckSpec, ctx: Context) -> str | None:
        a, b = (ctx.d.as_text(ctx.q(c)) for c in spec.columns)
        return f"{a} || ' > ' || {b}"

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        a, b = spec.columns
        return f"{k:,} rows in {spec.asset.label} have {a} after {b} ({pct(k, n)})."


class CasingVariants(Check):
    type = "sah.casing_variants"
    title = "Same value, different spelling"
    dimension = Dimension.CONSISTENCY
    severity = Severity.LOW
    evaluation = "python"
    next_step = "Normalise case in the pipeline or map variants to one code."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return (
            _is_text(col)
            and 2 <= (col.distinct or 0) <= 10_000
            and col.role not in KEYISH
            and col.semantic_type not in semantics.PERSONAL
        )

    def evaluate_values(
        self, spec: CheckSpec, values: list[tuple[str, int]]
    ) -> tuple[int, int, list[tuple[str, int]]]:
        groups: dict[str, list[tuple[str, int]]] = {}
        for v, c in values:
            groups.setdefault(v.strip().lower(), []).append((v, c))
        bad: list[tuple[str, int]] = []
        for variants in groups.values():
            if len(variants) > 1:
                variants.sort(key=lambda x: -x[1])
                bad += variants[1:]
        return sum(c for _, c in values), sum(c for _, c in bad), sorted(bad, key=lambda x: -x[1])[:5]

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} values in {where(spec)} are spelling variants of a more frequent value ({pct(k, n)})."


# --- uniqueness -----------------------------------------------------------------------------


class Unique(Check):
    type = "sah.unique"
    title = "Duplicate keys"
    dimension = Dimension.UNIQUENESS
    severity = Severity.CRITICAL
    next_step = "Find the double load; add a unique constraint where the store allows it."

    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return col.role == Role.KEY and col.logical_type.is_scalar

    def n_expr(self, spec: CheckSpec, ctx: Context) -> str:
        return f"count({ctx.q(spec.column or '')})"

    def k_expr(self, spec: CheckSpec, ctx: Context) -> str:
        q = ctx.q(spec.column or "")
        return f"count({q}) - count(DISTINCT {q})"

    def examples_sql(self, spec: CheckSpec, ctx: Context) -> str | None:
        q = ctx.q(spec.column or "")
        t = ctx.d.as_text(q)
        return ctx.rel.query(
            f"SELECT {t} AS v, count(*) AS n FROM {ctx.rel.ref} AS s WHERE {q} IS NOT NULL "
            f"GROUP BY {t} HAVING count(*) > 1 ORDER BY n DESC, v LIMIT 5"
        )

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} rows in {where(spec)} repeat a key that appears earlier ({pct(k, n)})."


class DuplicateRows(Check):
    type = "sah.duplicate_rows"
    title = "Identical rows"
    dimension = Dimension.UNIQUENESS
    level = "asset"
    severity = Severity.HIGH
    next_step = "Find the double load; add a unique constraint where the store allows it."

    def generate(self, ctx: Context) -> list[CheckSpec]:
        cols = [c.name for c in ctx.asset.columns if c.logical_type.is_scalar]
        return [self.spec(ctx, columns=cols)] if len(cols) >= 2 else []

    def n_expr(self, spec: CheckSpec, ctx: Context) -> str:
        return "count(*)"

    def k_expr(self, spec: CheckSpec, ctx: Context) -> str:
        cols = ", ".join(ctx.d.ident(c) for c in spec.columns)
        return f"count(*) - (SELECT count(*) FROM (SELECT DISTINCT {cols} FROM {ctx.rel.ref}) AS dd)"

    def examples_sql(self, spec: CheckSpec, ctx: Context) -> str | None:
        return None

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} rows in {spec.asset.label} are exact copies of another row ({pct(k, n)})."


# --- currentness ----------------------------------------------------------------------------

FRESH_NAMES = ("_at", "_time", "_date", "_ts", "timestamp", "loaded", "updated", "created")


class Freshness(Check):
    type = "sah.freshness"
    title = "Data not updated"
    dimension = Dimension.CURRENTNESS
    level = "asset"
    kind = "baseline"
    severity = Severity.HIGH
    evaluation = "profile"
    next_step = "Check the scheduler of the load that writes this table."

    def generate(self, ctx: Context) -> list[CheckSpec]:
        cands = [
            c
            for c in ctx.asset.columns
            if c.role == Role.TIMESTAMP
            and c.max is not None
            and (c.name.lower().endswith(FRESH_NAMES) or c.name.lower() in ("ts", "time", "date"))
        ]
        newest = max(cands, key=lambda c: str(c.max), default=None)
        if newest is None:
            return []
        dt = _iso_dt(newest.max)
        if dt is None:
            return []
        age_h = max(
            0.0, (ctx.scan_time.replace(tzinfo=None) - dt.replace(tzinfo=None)).total_seconds() / 3600
        )
        if age_h > 24 * 365:
            return []  # a historical table, not a feed
        return [self.spec(ctx, column=newest.name, params={"max_age_hours": max(24, math.ceil(2 * age_h))})]

    def evaluate_profile(self, spec: CheckSpec, ctx: Context) -> tuple[int, int, list[tuple[str, int]]]:
        q = ctx.d.ident(spec.column or "")
        newest = ctx.src.query(f"SELECT max({q}) FROM {ctx.rel.full}")[0][0]
        if newest is None:
            return 1, 1, []
        nd = newest if isinstance(newest, datetime) else datetime.fromisoformat(str(newest))
        age_h = (ctx.scan_time.replace(tzinfo=None) - nd.replace(tzinfo=None)).total_seconds() / 3600
        spec.params["age_hours"] = round(age_h, 1)
        return 1, int(age_h > spec.params["max_age_hours"]), [(str(newest), 1)]

    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        age = spec.params.get("age_hours")
        state = "older than" if k else "within"
        return (
            f"The newest {spec.column} in {spec.asset.label} is {age} h old, {state} the "
            f"{spec.params['max_age_hours']} h allowed."
        )


CATALOGUE: tuple[Check, ...] = (
    NotNull(),
    NotBlank(),
    RowCount(),
    TypeConformance(),
    SemanticFormat(),
    Pattern(),
    AcceptedValues(),
    Length(),
    Whitespace(),
    NonPrinting(),
    Range(),
    Outliers(),
    FutureDates(),
    ImplausibleDates(),
    ForeignKey(),
    ColumnOrder(),
    CasingVariants(),
    Unique(),
    DuplicateRows(),
    Freshness(),
)
BY_TYPE: dict[str, Check] = {c.type: c for c in CATALOGUE}
LEADING_ZERO = LEADING_ZERO_NUMBER
