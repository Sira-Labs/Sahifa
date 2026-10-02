"""Column profiles (spec 002): one aggregate query per asset, one grouped query for values."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from . import semantics
from .connectors.base import Connector, Relation
from .models import AssetInfo, AssetProfile, ColumnProfile, LogicalType, Role, ValueCount
from .sql import DATE_LIKE, LEADING_ZERO_NUMBER, NON_PRINTING_CLASS, NUMERIC_LIKE

TOP_VALUES_TEXT = 1000
TOP_VALUES_OTHER = 25
SHOWN_TOP = 20
SHOWN_PATTERNS = 10
QUANTILES = (0.01, 0.25, 0.5, 0.75, 0.99)


def pattern_class(value: str) -> str:
    """Letters become A, digits 9, other characters stay; runs of five or more collapse to X{5+}."""
    out: list[str] = []
    for ch in value:
        out.append("A" if ch.isalpha() else "9" if "0" <= ch <= "9" else ch)
    s = "".join(out)
    return re.sub(r"(A{5,}|9{5,})", lambda m: f"{m.group(0)[0]}{{5+}}", s)


def pattern_regex(pattern: str, letter: str) -> str:
    """The regular expression that matches values of `pattern` (`letter` is the dialect's letter class)."""
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("{5+}", i):
            parts.append("{5,}")
            i += 4
            continue
        ch = pattern[i]
        parts.append(letter if ch == "A" else "[0-9]" if ch == "9" else re.escape(ch))
        i += 1
    return "".join(parts)


def _singular(name: str) -> set[str]:
    n = name.lower()
    out = {n}
    if n.endswith("ies"):
        out.add(n[:-3] + "y")
    if n.endswith(("ses", "xes", "ches", "shes")):
        out.add(n[:-2])
    if n.endswith("s"):
        out.add(n[:-1])
    return out


def infer_role(col: ColumnProfile, info: AssetInfo) -> Role:
    name = col.name.lower()
    if col.name in info.primary_key or [col.name] in info.unique:
        return Role.KEY
    if any(fk.column == col.name for fk in info.foreign_keys):
        return Role.FOREIGN_KEY
    if col.logical_type.is_temporal:
        return Role.TIMESTAMP
    looks_unique = col.non_null > 0 and col.distinct_ratio >= 0.99
    if name == "id" and looks_unique:
        return Role.KEY
    if name.endswith("_id"):
        if any(name == f"{s}_id" for s in _singular(info.ref.name)) and looks_unique:
            return Role.KEY
        return Role.FOREIGN_KEY
    if col.logical_type.is_numeric:
        return Role.MEASURE
    if col.logical_type == LogicalType.TEXT and (col.mean_length or 0) > 50:
        return Role.DESCRIPTION
    return Role.ATTRIBUTE


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal | int | float):
        return float(v)
    return None


def _scalar(v: Any) -> float | str | None:
    if v is None:
        return None
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal | int | float):
        return float(v)
    return str(v)


def _int(v: Any) -> int:
    return int(v or 0)


def profile_asset(
    src: Connector,
    info: AssetInfo,
    rel: Relation,
    population: int,
    population_exact: bool,
    scan_time: datetime,
) -> AssetProfile:
    """Measure every column of the sampled relation."""
    d = src.dialect
    exprs: list[str] = ["count(*)"]
    layout: list[tuple[str, int, int]] = []  # (column, start index, count)
    future = d.timestamp(scan_time + timedelta(days=1))
    y1900 = d.timestamp(datetime(1900, 1, 1))
    y2200 = d.timestamp(datetime(2200, 1, 1))
    for c in info.columns:
        q = f"s.{d.ident(c.name)}"
        part = [f"count({q})"]
        if c.logical_type.is_scalar:
            part.append(f"count(DISTINCT {q})")
        if c.logical_type.is_numeric:
            x = d.as_double(q)
            part += [
                f"min({q})",
                f"max({q})",
                f"avg({x})",
                f"stddev_samp({x})",
                d.quantiles(x, QUANTILES),
                d.sum_case(f"{q} = 0"),
                d.sum_case(f"{q} < 0"),
            ]
        elif c.logical_type == LogicalType.TEXT:
            t = d.as_text(q)
            part += [
                f"min(length({t}))",
                f"max(length({t}))",
                f"avg(length({t}))",
                d.sum_case(f"{t} <> trim({t})"),
                d.sum_case(d.regex_search(t, NON_PRINTING_CLASS)),
                d.sum_case(d.is_blank(t)),
                d.sum_case(d.regex_full(t, NUMERIC_LIKE)),
                d.sum_case(d.regex_full(t, DATE_LIKE)),
                d.sum_case(d.regex_full(t, LEADING_ZERO_NUMBER)),
            ]
        elif c.logical_type.is_temporal:
            part += [
                f"min({q})",
                f"max({q})",
                d.sum_case(f"{q} > {future}"),
                d.sum_case(f"{q} < {y1900}"),
                d.sum_case(f"{q} > {y2200}"),
            ]
        layout.append((c.name, len(exprs), len(part)))
        exprs += part
    row = src.query(rel.query(f"SELECT {', '.join(exprs)} FROM {rel.ref} AS s"))[0]
    rows = _int(row[0])
    profiles: list[ColumnProfile] = []
    for c, (_, start, _n) in zip(info.columns, layout, strict=True):
        v = row[start : start + _n]
        p = ColumnProfile(
            name=c.name,
            position=c.position,
            physical_type=c.physical_type,
            logical_type=c.logical_type,
            declared_not_null=c.declared_not_null,
            rows=rows,
            nulls=rows - _int(v[0]),
        )
        i = 1
        if c.logical_type.is_scalar:
            p.distinct = _int(v[1])
            i = 2
        if c.logical_type.is_numeric:
            p.min, p.max, p.mean, p.stddev = _scalar(v[i]), _scalar(v[i + 1]), _num(v[i + 2]), _num(v[i + 3])
            qs = v[i + 4]
            if qs:
                p.quantiles = {
                    f"p{int(q * 100):02d}": float(x)
                    for q, x in zip(QUANTILES, qs, strict=True)
                    if x is not None
                }
            p.zeros, p.negatives = _int(v[i + 5]), _int(v[i + 6])
        elif c.logical_type == LogicalType.TEXT:
            p.min_length, p.max_length = (
                int(v[i]) if v[i] is not None else None,
                int(v[i + 1]) if v[i + 1] is not None else None,
            )
            p.mean_length = _num(v[i + 2])
            (p.whitespace, p.non_printing, p.blanks, p.numeric_like, p.date_like, p.leading_zero_numbers) = (
                _int(x) for x in v[i + 3 : i + 9]
            )
        elif c.logical_type.is_temporal:
            p.min, p.max = _scalar(v[i]), _scalar(v[i + 1])
            p.future, p.before_1900, p.after_2200 = _int(v[i + 2]), _int(v[i + 3]), _int(v[i + 4])
            newest = _scalar(v[i + 1])
            p.newest = newest if isinstance(newest, str) else None
        profiles.append(p)

    _values(src, rel, profiles)
    _mad(src, rel, profiles)
    for p in profiles:
        p.role = infer_role(p, info)
    asset = AssetProfile(
        ref=info.ref,
        population=population,
        population_exact=population_exact,
        sample_rows=rows,
        sampled=rel.method != "full",
        columns=profiles,
        primary_key=info.primary_key,
        unique=info.unique,
        foreign_keys=info.foreign_keys,
        declared_metadata=bool(info.primary_key or info.foreign_keys or info.unique),
    )
    asset.time_series_candidate = (
        any(p.role == Role.TIMESTAMP for p in profiles)
        and any(p.role == Role.MEASURE for p in profiles)
        and rows >= 100
    )
    return asset


def _values(src: Connector, rel: Relation, profiles: list[ColumnProfile]) -> None:
    """Top values for every scalar column in one UNION ALL query; patterns and semantics from them."""
    d = src.dialect
    parts = []
    targets = [p for p in profiles if p.logical_type.is_scalar and p.non_null > 0]
    for i, p in enumerate(targets):
        q = f"s.{d.ident(p.name)}"
        limit = TOP_VALUES_TEXT if p.logical_type == LogicalType.TEXT else TOP_VALUES_OTHER
        parts.append(
            f"SELECT * FROM (SELECT {i} AS c, {d.as_text(q)} AS v, count(*) AS n FROM {rel.ref} AS s "
            f"WHERE {q} IS NOT NULL GROUP BY {d.as_text(q)} ORDER BY n DESC, v LIMIT {limit}) AS t{i}"
        )
    if not parts:
        return
    grouped: dict[int, list[tuple[str, int]]] = {}
    for c, v, n in src.query(rel.query(" UNION ALL ".join(parts))):
        grouped.setdefault(int(c), []).append((str(v), int(n)))
    for i, p in enumerate(targets):
        values = grouped.get(i, [])
        fetched = sum(n for _, n in values)
        p.top_truncated = fetched < p.non_null
        personal = False
        if p.logical_type == LogicalType.TEXT:
            p.semantic_type, p.semantic_share = semantics.infer(p.name, values)
            personal = p.semantic_type in semantics.PERSONAL
            counts: dict[str, int] = {}
            for v, n in values:
                pc = pattern_class(v)
                counts[pc] = counts.get(pc, 0) + n
            p.patterns = [
                ValueCount(value=k, count=n)
                for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:SHOWN_PATTERNS]
            ]
        p.top = [
            ValueCount(value=semantics.mask(v) if personal else v, count=n, masked=personal)
            for v, n in values[:SHOWN_TOP]
        ]


def _mad(src: Connector, rel: Relation, profiles: list[ColumnProfile]) -> None:
    d = src.dialect
    targets = [p for p in profiles if p.logical_type.is_numeric and p.quantiles and "p50" in p.quantiles]
    if not targets:
        return
    exprs = [
        d.median(f"abs({d.as_double('s.' + d.ident(p.name))} - {d.literal(p.quantiles['p50'])})")
        for p in targets
        if p.quantiles
    ]
    row = src.query(rel.query(f"SELECT {', '.join(exprs)} FROM {rel.ref} AS s"))[0]
    for p, v in zip(targets, row, strict=True):
        p.mad = _num(v)


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
