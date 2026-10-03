"""One scan of a source (spec 003): discover → sample → profile → check → score → report."""

from __future__ import annotations

import logging
import queue
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from . import semantics
from .checks import BY_TYPE, CATALOGUE, Check, Context
from .checks.base import pct
from .checks.lifecycle import keeps_saved, reconcile
from .connectors import Connector, Relation, open_source
from .errors import SahifaError
from .models import (
    AssetProfile,
    AssetRef,
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
    UnevaluatedCheck,
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
T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class ScanOptions:
    sample_rows: int = 100_000
    seed: int = 42
    assets: tuple[str, ...] | None = None
    memory_limit: str = "1GB"
    statement_timeout_s: int = 60
    # Assets scanned at once, each on its own read-only session (spec 013). Postgres only: a
    # DuckDB source keeps its samples as temporary tables of one connection and parallelises
    # each query itself.
    workers: int = 2


@dataclass
class _Scanned:
    """What phase one keeps of an asset: its profile and, unless it failed, its sample."""

    profile: AssetProfile
    relation: Relation | None = None


@dataclass
class _Evaluated:
    report: AssetReport
    dims: dict[Dimension, Estimate] | None
    results: list[CheckResult]
    specs: list[CheckSpec]


class _Pool:
    """The scan's source sessions: the first one opened by the caller, `workers - 1` more for a
    Postgres source. Each task borrows one, so no session is used by two threads at once."""

    def __init__(self, first: Connector, extra: list[Connector]) -> None:
        self.all = [first, *extra]
        self.free: queue.Queue[Connector] = queue.Queue()
        for c in self.all:
            self.free.put(c)

    def map(self, fn: Callable[[Connector, T], R], items: list[T]) -> list[R]:
        """`fn(session, item)` for every item, on as many sessions as there are, in order."""

        def run(item: T) -> R:
            con = self.free.get()
            try:
                return fn(con, item)
            finally:
                self.free.put(con)

        if len(self.all) == 1:
            return [run(i) for i in items]
        with ThreadPoolExecutor(max_workers=len(self.all), thread_name_prefix="sahifa-scan") as ex:
            return list(ex.map(run, items))

    @property
    def queries(self) -> int:
        return sum(c.queries for c in self.all)


def run_scan(
    source: str | list[str],
    options: ScanOptions | None = None,
    *,
    scan_id: str | None = None,
    names: dict[str, str] | None = None,
    saved: Mapping[str, list[CheckSpec]] | None = None,
) -> ScanReport:
    """Assess every asset of `source` and return the report. Raises `SahifaError` when the
    source cannot be opened; a failing asset is recorded in the report and the scan goes on.

    `saved` holds the stored checks per asset label (spec 007); they are reconciled with the
    generated ones. Without it every check is generated afresh.

    Phase one profiles every asset; phase two evaluates the checks, which may look at other
    assets' profiles (foreign keys). Each phase runs on `options.workers` sessions (spec 013);
    the report is the same whatever their number."""
    options = options or ScanOptions()
    scan_id = scan_id or str(uuid.uuid4())
    started = datetime.now(UTC).replace(microsecond=0)
    t0 = time.monotonic()

    def connect(worker: int) -> Connector:
        return open_source(
            source,
            names=names,
            memory_limit=options.memory_limit,
            statement_timeout_s=options.statement_timeout_s,
            application_name=f"sahifa/{scan_id}" + (f"/{worker}" if worker else ""),
        )

    with connect(0) as src:
        extra = [connect(i) for i in range(1, max(1, options.workers))] if src.kind == "postgres" else []
        pool = _Pool(src, extra)
        try:
            refs = src.list_assets()
            if options.assets:
                wanted = set(options.assets)
                refs = [r for r in refs if r.label in wanted or r.name in wanted]

            def scan_one(con: Connector, ref: AssetRef) -> _Scanned:
                t = time.monotonic()
                before = con.queries
                try:
                    info = con.describe(ref)
                    population, exact = con.count_rows(ref, info)
                    rel = con.sample(ref, options.sample_rows, options.seed, population)
                    out = _Scanned(profile_asset(con, info, rel, population, exact, started), rel)
                except SahifaError as e:
                    log.warning("asset.failed %s: %s", ref.label, e)
                    out = _Scanned(AssetProfile(ref=ref, error=str(e)))
                _timing[ref.label] = [time.monotonic() - t, con.queries - before]
                return out

            _timing: dict[str, list[float]] = {}
            scanned = dict(zip((r.label for r in refs), pool.map(scan_one, refs), strict=True))
            profiles = {label: s.profile for label, s in scanned.items()}

            def evaluate_one(con: Connector, label: str) -> _Evaluated:
                t = time.monotonic()
                before = con.queries
                prof, rel = profiles[label], scanned[label].relation
                if prof.error or rel is None:
                    report = AssetReport(
                        ref=prof.ref,
                        population=0,
                        population_exact=False,
                        sample_rows=0,
                        sampled=False,
                        score=to_score({}),
                        error=prof.error,
                    )
                    return _Evaluated(report, None, [], [])
                ctx = Context(asset=prof, assets=profiles, src=con, rel=rel, scan_time=started)
                try:
                    evaluation = evaluate_asset(ctx, (saved or {}).get(label))
                except SahifaError as e:
                    log.warning("asset.checks_failed %s: %s", label, e)
                    prof.error = str(e)
                    evaluation = AssetEvaluation()
                finally:
                    con.release(rel)
                report, dims = asset_report(prof, evaluation.results)
                report.unevaluated = evaluation.unevaluated
                seconds, queries = _timing[label]
                seconds += time.monotonic() - t
                queries += con.queries - before
                _timing[label] = [seconds, queries]
                report.duration_s, report.queries = round(seconds, 3), int(queries)
                log.info("asset.scanned %s: %.2f s, %d queries", label, seconds, queries)
                return _Evaluated(report, dims, evaluation.results, evaluation.specs)

            evaluated = pool.map(evaluate_one, list(profiles))
        finally:
            for con in extra:
                con.close()
        assets = [e.report for e in evaluated]
        asset_dims = [(e.report, e.dims) for e in evaluated if e.dims is not None]
        results_all = [r for e in evaluated for r in e.results]
        specs_all = [s for e in evaluated for s in e.specs]
        per_asset = [int(q) for _s, q in _timing.values()]
        stats = ScanStats(
            assets=len(profiles),
            assets_failed=sum(1 for p in profiles.values() if p.error),
            columns=sum(len(p.columns) for p in profiles.values()),
            checks_active=sum(1 for r in results_all if r.spec.status.scores),
            checks_proposed=sum(1 for r in results_all if not r.spec.status.scores),
            queries=pool.queries,
            queries_per_asset_max=max(per_asset, default=0),
            queries_per_asset_mean=round(sum(per_asset) / len(per_asset), 1) if per_asset else 0.0,
            workers=len(pool.all),
        )
        kind, label = src.kind, src.label

    store_dims = store_dimensions(asset_dims)
    findings = sorted(
        (finding_of(r) for r in results_all if is_finding(r)),
        key=lambda f: (list(SEVERITY_ORDER).index(f.severity), f.ratio),
    )
    stats.duration_s = round(time.monotonic() - t0, 2)
    log.info("scan.stats %s", stats.model_dump_json())
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
        checks=specs_all,
        stats=stats,
    )


SEVERITY_ORDER = ("critical", "high", "medium", "low")
# Spec 013: example queries per asset; failing checks past this many get none.
EXAMPLES_PER_ASSET = 10


@dataclass
class AssetEvaluation:
    """What `evaluate_asset` found for one asset."""

    # The reconciled specs as they were before evaluation (the API persists these).
    specs: list[CheckSpec] = field(default_factory=list)
    results: list[CheckResult] = field(default_factory=list)
    unevaluated: list[UnevaluatedCheck] = field(default_factory=list)


def missing_reason(s: CheckSpec, ctx: Context) -> str | None:
    """Why a (saved) check cannot run against this asset now, or None when it can."""
    if s.type not in BY_TYPE:
        return "unknown_type"
    present = {c.name for c in ctx.asset.columns}
    if any(c not in present for c in [s.column or "", *s.columns] if c):
        return "column_missing"
    parent = s.params.get("parent") if s.type == "sah.foreign_key" else None
    if parent is not None and parent not in ctx.assets:
        return "parent_missing"
    return None


def evaluate_asset(ctx: Context, saved: list[CheckSpec] | None = None) -> AssetEvaluation:
    """Generate the asset's checks, reconcile them with the saved ones and evaluate the result.

    Retired checks are not evaluated. A saved check whose column (or parent table) is gone is
    listed as unevaluated instead of failing the asset."""
    generated = [s for c in CATALOGUE for s in c.generate(ctx)]
    out = AssetEvaluation()
    specs: list[tuple[Check, CheckSpec]] = []
    for s in reconcile(generated, saved or []):
        reason = missing_reason(s, ctx)
        if reason is not None:
            out.specs.append(s)
            out.unevaluated.append(UnevaluatedCheck(spec=s, reason=reason))  # type: ignore[arg-type]
            continue
        # Evaluate a copy: profile checks note what they measured in their params.
        specs.append((BY_TYPE[s.type], s.model_copy(deep=True)))
        out.specs.append(s)
    counts: dict[str, tuple[int, int, list[tuple[str, int]]]] = {}
    sql_specs = [(c, s) for c, s in specs if c.evaluation == "sql"]
    if sql_specs:
        exprs = [f"{c.n_expr(s, ctx)}, {'0' if c.own_query else c.k_expr(s, ctx)}" for c, s in sql_specs]
        row = ctx.src.query(ctx.rel.query(f"SELECT {', '.join(exprs)} FROM {ctx.rel.ref} AS s"))[0]
        for i, (c, s) in enumerate(sql_specs):
            k = int(ctx.src.query(c.k_query(s, ctx))[0][0] or 0) if c.own_query else int(row[2 * i + 1] or 0)
            counts[s.id] = (int(row[2 * i] or 0), k, [])
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

    dropped: set[str] = set()
    kept = []
    for c, s in specs:
        n, k, _examples = counts[s.id]
        # Weak evidence drops a generated candidate; a locked or manual one is the owner's call.
        if not keeps_saved(s) and not c.accept(s, n, k):
            dropped.add(s.id)
            continue
        kept.append((c, s))
    # Examples for at most EXAMPLES_PER_ASSET failing SQL checks: those that score (findings)
    # before proposals, the most severe first.
    wants = [(c, s) for c, s in kept if counts[s.id][1] > 0 and c.evaluation == "sql" and not counts[s.id][2]]
    wants.sort(key=lambda cs: (not cs[1].status.scores, list(SEVERITY_ORDER).index(cs[1].severity)))
    fetch = {s.id for _c, s in wants[:EXAMPLES_PER_ASSET]}
    for c, s in kept:
        n, k, examples = counts[s.id]
        skipped = False
        if k > 0 and c.evaluation == "sql" and not examples:
            sql = c.examples_sql(s, ctx) if s.id in fetch else None
            if sql:
                examples = [(str(v), int(m)) for v, m in ctx.src.query(sql)]
            skipped = s.id not in fetch
        result = result_of(c, s, n, k, examples, ctx)
        result.examples_skipped = skipped
        out.results.append(result)
    out.specs = [s for s in out.specs if s.id not in dropped]
    return out


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
        examples_skipped=r.examples_skipped,
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
