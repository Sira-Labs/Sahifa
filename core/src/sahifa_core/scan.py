"""One scan of a source (spec 003): discover → sample → profile → check → score → report."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import semantics
from .checks import CATALOGUE, Check, Context
from .checks.base import pct
from .connectors import Relation, open_source
from .errors import SahifaError
from .models import (
    AssetProfile,
    AssetReport,
    CheckResult,
    CheckSpec,
    ColumnReport,
    Dimension,
    Finding,
    HealthItem,
    LogicalType,
    Role,
    ScanOptionsModel,
    ScanReport,
    ScanStats,
    SourceInfo,
    ValueCount,
)
from .profile import profile_asset
from .score import (
    ROLE_WEIGHT,
    Estimate,
    asset_weight,
    check_interval,
    product,
    to_score,
    variance_of,
    weighted_mean,
)

log = logging.getLogger("sahifa_core.scan")


@dataclass(frozen=True)
class ScanOptions:
    sample_rows: int = 100_000
    seed: int = 42
    assets: tuple[str, ...] | None = None
    memory_limit: str = "1GB"
    statement_timeout_s: int = 60


def run_scan(
    source: str | list[str],
    options: ScanOptions | None = None,
    *,
    scan_id: str | None = None,
    names: dict[str, str] | None = None,
) -> ScanReport:
    """Assess every asset of `source` and return the report. Raises `SahifaError` when the
    source cannot be opened; a failing asset is recorded in the report and the scan goes on."""
    options = options or ScanOptions()
    scan_id = scan_id or str(uuid.uuid4())
    started = datetime.now(UTC).replace(microsecond=0)
    t0 = time.monotonic()
    with open_source(
        source,
        names=names,
        memory_limit=options.memory_limit,
        statement_timeout_s=options.statement_timeout_s,
        application_name=f"sahifa/{scan_id}",
    ) as src:
        refs = src.list_assets()
        if options.assets:
            wanted = set(options.assets)
            refs = [r for r in refs if r.label in wanted or r.name in wanted]
        profiles: dict[str, AssetProfile] = {}
        relations: dict[str, Relation] = {}
        for ref in refs:
            try:
                info = src.describe(ref)
                population, exact = src.count_rows(ref, info)
                rel = src.sample(ref, options.sample_rows, options.seed, population)
                profiles[ref.label] = profile_asset(src, info, rel, population, exact, started)
                relations[ref.label] = rel
            except SahifaError as e:
                log.warning("asset.failed %s: %s", ref.label, e)
                profiles[ref.label] = AssetProfile(ref=ref, error=str(e))

        assets: list[AssetReport] = []
        asset_dims: list[tuple[AssetReport, dict[Dimension, Estimate]]] = []
        results_all: list[CheckResult] = []
        for label, prof in profiles.items():
            if prof.error or label not in relations:
                assets.append(
                    AssetReport(
                        ref=prof.ref,
                        population=0,
                        population_exact=False,
                        sample_rows=0,
                        sampled=False,
                        score=to_score({}),
                        error=prof.error,
                    )
                )
                continue
            ctx = Context(asset=prof, assets=profiles, src=src, rel=relations[label], scan_time=started)
            try:
                results = evaluate_asset(ctx)
            except SahifaError as e:
                log.warning("asset.checks_failed %s: %s", label, e)
                prof.error = str(e)
                results = []
            finally:
                src.release(relations[label])
            results_all += results
            report, dims = asset_report(prof, results)
            assets.append(report)
            asset_dims.append((report, dims))
        stats = ScanStats(
            assets=len(profiles),
            assets_failed=sum(1 for p in profiles.values() if p.error),
            columns=sum(len(p.columns) for p in profiles.values()),
            checks_active=sum(1 for r in results_all if r.spec.status.scores),
            checks_proposed=sum(1 for r in results_all if not r.spec.status.scores),
            queries=src.queries,
        )
        kind, label = src.kind, src.label

    store_dims = store_dimensions(asset_dims)
    findings = sorted(
        (finding_of(r) for r in results_all if is_finding(r)),
        key=lambda f: (list(SEVERITY_ORDER).index(f.severity), f.ratio),
    )
    stats.duration_s = round(time.monotonic() - t0, 2)
    return ScanReport(
        scan_id=scan_id,
        started_at=started,
        finished_at=datetime.now(UTC).replace(microsecond=0),
        source=SourceInfo(kind=kind, label=label),
        options=ScanOptionsModel(sample_rows=options.sample_rows, seed=options.seed),
        score=to_score(store_dims),
        assets=assets,
        findings=findings,
        health=health_items(list(profiles.values()), kind),
        proposed=[r for r in results_all if not r.spec.status.scores],
        stats=stats,
    )


SEVERITY_ORDER = ("critical", "high", "medium", "low")


def evaluate_asset(ctx: Context) -> list[CheckResult]:
    specs: list[tuple[Check, CheckSpec]] = [(c, s) for c in CATALOGUE for s in c.generate(ctx)]
    counts: dict[str, tuple[int, int, list[tuple[str, int]]]] = {}
    sql_specs = [(c, s) for c, s in specs if c.evaluation == "sql"]
    if sql_specs:
        exprs = [f"{c.n_expr(s, ctx)}, {c.k_expr(s, ctx)}" for c, s in sql_specs]
        row = ctx.src.query(ctx.rel.query(f"SELECT {', '.join(exprs)} FROM {ctx.rel.ref} AS s"))[0]
        for i, (_, s) in enumerate(sql_specs):
            counts[s.id] = (int(row[2 * i] or 0), int(row[2 * i + 1] or 0), [])
    py_specs = [(c, s) for c, s in specs if c.evaluation == "python"]
    values_cache: dict[str, list[tuple[str, int]]] = {}
    for c, s in py_specs:
        col = s.column or ""
        if col not in values_cache:
            values_cache[col] = grouped_values(ctx, col)
        counts[s.id] = c.evaluate_values(s, values_cache[col])
    for c, s in specs:
        if c.evaluation == "profile":
            counts[s.id] = c.evaluate_profile(s, ctx)

    results = []
    for c, s in specs:
        n, k, examples = counts[s.id]
        if not c.accept(s, n, k):
            continue
        if k > 0 and c.evaluation == "sql" and not examples:
            sql = c.examples_sql(s, ctx)
            if sql:
                examples = [(str(v), int(m)) for v, m in ctx.src.query(sql)]
        results.append(result_of(c, s, n, k, examples, ctx))
    return results


def grouped_values(ctx: Context, column: str) -> list[tuple[str, int]]:
    q = ctx.q(column)
    t = ctx.d.as_text(q)
    rows = ctx.src.query(
        ctx.rel.query(
            f"SELECT {t} AS v, count(*) AS n FROM {ctx.rel.ref} AS s WHERE {q} IS NOT NULL "
            f"GROUP BY {t} ORDER BY n DESC, v LIMIT {MAX_GROUPS}"
        )
    )
    return [(str(v), int(n)) for v, n in rows]


MAX_GROUPS = 50_000


def result_of(
    c: Check, s: CheckSpec, n: int, k: int, examples: list[tuple[str, int]], ctx: Context
) -> CheckResult:
    population = n
    if c.level == "column" or s.columns:
        # Row-level checks: scale the evaluated count to the asset's population.
        rows = max(ctx.asset.sample_rows, 1)
        population = max(n, round(n * ctx.asset.population / rows)) if ctx.asset.sampled else n
    ratio, low, high = check_interval(n, k, population)
    col = ctx.asset.column(s.column) if s.column else None
    personal = bool(col and col.semantic_type in semantics.PERSONAL)
    shown = [
        ValueCount(value=semantics.mask(v) if personal else v[:200], count=m, masked=personal)
        for v, m in examples[:5]
    ]
    passed = ratio >= 1 - s.max_fail_ratio - 1e-12 if k else True
    sql = None
    if c.evaluation == "sql" and k:
        sql = c.examples_sql(s, ctx) or ctx.rel.query(
            f"SELECT {c.n_expr(s, ctx)} AS evaluated, {c.k_expr(s, ctx)} AS failed FROM {ctx.rel.ref} AS s"
        )
    return CheckResult(
        spec=s,
        evaluated=n,
        failed=k,
        population=population,
        ratio=ratio,
        low=low,
        high=high,
        passed=passed,
        summary=c.summary(s, n, k),
        next_step=c.next_step,
        examples=shown,
        sql=sql,
        truncated=c.evaluation == "python" and n < (col.non_null if col else n),
    )


def is_finding(r: CheckResult) -> bool:
    return r.spec.status.scores and r.failed > 0 and not r.passed


def finding_of(r: CheckResult) -> Finding:
    from .checks import BY_TYPE

    return Finding(
        check_id=r.spec.id,
        check_type=r.spec.type,
        title=BY_TYPE[r.spec.type].title,
        asset=r.spec.asset.label,
        column=r.spec.column or (", ".join(r.spec.columns) or None),
        dimension=r.spec.dimension,
        severity=r.spec.severity,
        evaluated=r.evaluated,
        failed=r.failed,
        ratio=r.ratio,
        low=r.low,
        high=r.high,
        summary=r.summary,
        next_step=r.next_step,
        examples=r.examples,
        sql=r.sql,
    )


def _estimate(r: CheckResult) -> tuple[float, float, float]:
    return r.ratio, variance_of(r.low, r.high), r.spec.severity.weight


def asset_report(
    prof: AssetProfile, results: list[CheckResult]
) -> tuple[AssetReport, dict[Dimension, Estimate]]:
    scored = [r for r in results if r.spec.status.scores]
    columns: list[ColumnReport] = []
    col_dims: dict[str, dict[Dimension, Estimate]] = {}
    for col in prof.columns:
        dims: dict[Dimension, Estimate] = {}
        for d in Dimension:
            est = product(_estimate(r) for r in scored if r.spec.column == col.name and r.spec.dimension == d)
            if est:
                dims[d] = est
        col_dims[col.name] = dims
        columns.append(ColumnReport(profile=col, score=to_score(dims)))
    asset_dims: dict[Dimension, Estimate] = {}
    for d in Dimension:
        mean = weighted_mean(
            (col_dims[c.name][d], ROLE_WEIGHT[c.role]) for c in prof.columns if d in col_dims[c.name]
        )
        table = product(_estimate(r) for r in scored if not r.spec.column and r.spec.dimension == d)
        if mean and table:
            v = mean.value * table.value
            var = (table.value**2) * mean.var + (mean.value**2) * table.var
            asset_dims[d] = Estimate(v, var, mean.checks + table.checks)
        elif mean or table:
            asset_dims[d] = mean or table  # type: ignore[assignment]
    report = AssetReport(
        ref=prof.ref,
        population=prof.population,
        population_exact=prof.population_exact,
        sample_rows=prof.sample_rows,
        sampled=prof.sampled,
        score=to_score(asset_dims),
        columns=columns,
        checks=results,
        time_series_candidate=prof.time_series_candidate,
    )
    return report, asset_dims


def store_dimensions(
    assets: list[tuple[AssetReport, dict[Dimension, Estimate]]],
) -> dict[Dimension, Estimate]:
    out: dict[Dimension, Estimate] = {}
    for d in Dimension:
        est = weighted_mean((dims[d], asset_weight(a.population)) for a, dims in assets if d in dims)
        if est:
            out[d] = est
    return out


def health_items(profiles: list[AssetProfile], kind: str) -> list[Any]:
    items: list[HealthItem] = []
    for p in profiles:
        if p.error:
            continue
        if p.population == 0:
            items.append(
                HealthItem(type="store.empty_table", asset=p.ref.label, summary=f"{p.ref.label} has no rows.")
            )
        if kind == "postgres" and p.ref.kind == "table" and not p.primary_key:
            items.append(
                HealthItem(
                    type="store.no_primary_key",
                    asset=p.ref.label,
                    summary=f"{p.ref.label} has no declared primary key.",
                )
            )
        for c in p.columns:
            if (
                c.logical_type == LogicalType.TEXT
                and c.non_null > 0
                and c.numeric_like == c.non_null
                and not c.leading_zero_numbers
                and c.role not in (Role.KEY, Role.FOREIGN_KEY)
            ):
                items.append(
                    HealthItem(
                        type="store.numbers_as_text",
                        asset=p.ref.label,
                        column=c.name,
                        summary=f"{p.ref.label}.{c.name} stores numbers as text "
                        f"({pct(c.non_null, c.non_null)} of values are numeric).",
                    )
                )
    return items
