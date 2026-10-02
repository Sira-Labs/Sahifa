"""SQL rendering per engine (ADR-0001).

Every query the core sends is built here or from these helpers. Identifiers are quoted and
literals rendered by SQLGlot for the target dialect; a value read from the data never reaches
SQL text any other way. The handful of functions that differ between engines (regular
expressions, casts, quantiles, sampling) have one method each.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime

from sqlglot import exp

from .errors import UnsafeValueError
from .models import AssetRef

# Characters `sah.non_printing` looks for: C0 controls except tab, LF and CR, DEL, no-break
# space, zero-width space and the byte-order mark. Written as the characters themselves in a
# bracket expression, which RE2 (DuckDB) and Postgres ARE both accept.
NON_PRINTING_CLASS = (
    "["
    + "\x01-\x08"
    + "\x0b\x0c"
    + "\x0e-\x1f"
    + "\x7f"
    + " ​﻿"
    + "]"
)

NUMERIC_LIKE = r"\s*[-+]?([0-9]+([.,][0-9]+)?|[.,][0-9]+)([eE][-+]?[0-9]+)?\s*"
DATE_LIKE = (
    r"\s*([0-9]{4}-[0-9]{2}-[0-9]{2}([ T][0-9]{2}:[0-9]{2}(:[0-9]{2}([.][0-9]+)?)?"
    r"(Z|[+-][0-9]{2}:?[0-9]{2})?)?|[0-9]{1,2}[./][0-9]{1,2}[./]([0-9]{4}|[0-9]{2}))\s*"
)
LEADING_ZERO_NUMBER = r"0[0-9]+"
BLANK_TOKENS = ("n/a", "na", "null", "none", "nil", "-", "--", "?", "unknown", "undefined", "#n/a")


class Dialect:
    """Base dialect; subclasses override what differs."""

    name = "generic"
    sqlglot_name = ""
    text_type = "VARCHAR"
    double_type = "DOUBLE"

    def ident(self, name: str) -> str:
        if "\x00" in name:
            raise UnsafeValueError("identifier contains NUL")
        return exp.to_identifier(name, quoted=True).sql(dialect=self.sqlglot_name)

    def table(self, ref: AssetRef) -> str:
        if ref.namespace:
            return f"{self.ident(ref.namespace)}.{self.ident(ref.name)}"
        return self.ident(ref.name)

    def literal(self, value: str | int | float | bool | None) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int | float):
            if isinstance(value, float) and not math.isfinite(value):
                raise UnsafeValueError("non-finite number")
            return exp.Literal.number(repr(value)).sql(dialect=self.sqlglot_name)
        if "\x00" in value:
            raise UnsafeValueError("string contains NUL")
        return exp.Literal.string(value).sql(dialect=self.sqlglot_name)

    def literal_list(self, values: Sequence[str | int | float | bool]) -> str:
        return "(" + ", ".join(self.literal(v) for v in values) + ")"

    def timestamp(self, value: datetime) -> str:
        naive = value.replace(tzinfo=None) if value.tzinfo else value
        return f"TIMESTAMP {self.literal(naive.isoformat(sep=' ', timespec='seconds'))}"

    def as_text(self, expr: str) -> str:
        return f"CAST({expr} AS {self.text_type})"

    def as_double(self, expr: str) -> str:
        return f"CAST({expr} AS {self.double_type})"

    def regex_full(self, expr: str, pattern: str) -> str:
        raise NotImplementedError

    def regex_search(self, expr: str, pattern: str) -> str:
        raise NotImplementedError

    def quantiles(self, expr: str, probs: Sequence[float]) -> str:
        raise NotImplementedError

    def median(self, expr: str) -> str:
        raise NotImplementedError

    def is_blank(self, expr: str) -> str:
        """True for empty, whitespace-only and placeholder text (`sah.not_blank`)."""
        trimmed = f"trim({expr})"
        return f"({trimmed} = '' OR lower({trimmed}) IN {self.literal_list(BLANK_TOKENS)})"

    def sum_case(self, predicate: str) -> str:
        return f"SUM(CASE WHEN {predicate} THEN 1 ELSE 0 END)"


class DuckDBDialect(Dialect):
    name = "duckdb"
    sqlglot_name = "duckdb"
    text_type = "VARCHAR"
    double_type = "DOUBLE"

    def regex_full(self, expr: str, pattern: str) -> str:
        return f"regexp_full_match({expr}, {self.literal(pattern)})"

    def regex_search(self, expr: str, pattern: str) -> str:
        return f"regexp_matches({expr}, {self.literal(pattern)})"

    def quantiles(self, expr: str, probs: Sequence[float]) -> str:
        return f"quantile_cont({expr}, [{', '.join(repr(p) for p in probs)}])"

    def median(self, expr: str) -> str:
        return f"median({expr})"


class PostgresDialect(Dialect):
    name = "postgres"
    sqlglot_name = "postgres"
    text_type = "TEXT"
    double_type = "DOUBLE PRECISION"

    def regex_full(self, expr: str, pattern: str) -> str:
        return f"({expr} ~ {self.literal('^(' + pattern + ')$')})"

    def regex_search(self, expr: str, pattern: str) -> str:
        return f"({expr} ~ {self.literal(pattern)})"

    def quantiles(self, expr: str, probs: Sequence[float]) -> str:
        arr = ", ".join(repr(p) for p in probs)
        return f"percentile_cont(ARRAY[{arr}]::double precision[]) WITHIN GROUP (ORDER BY {expr})"

    def median(self, expr: str) -> str:
        return f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {expr})"


DIALECTS: dict[str, Dialect] = {"duckdb": DuckDBDialect(), "postgres": PostgresDialect()}
