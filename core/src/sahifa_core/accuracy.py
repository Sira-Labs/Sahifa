"""Accuracy benchmark per check (spec 014): how well each R1 check finds the faults known to be
in the synthetic shop, and how often it flags data nobody broke.

Per seed it runs five scans, all on DuckDB files in a temporary directory:

- A, the faulty shop: rule checks against its fault list (detection, exact count, unexpected).
- B, the clean twin: rule checks that count anything are false alarms.
- C, the drift twin, against the baselines B proposed, locked: baseline checks against the
  drift faults.
- D, a clean shop of another seed against the same locked baselines: findings there are false
  alarms of a baseline on legitimate new data.
- E, the faulty shop sampled: detection, and whether each 95 % interval holds the full-read pass
  ratio of run A.

Results match faults by check type, asset name and column (asset-level checks by asset alone).
A failing count is measured whether or not it raises a finding: the benchmark measures the
detector, the thresholds belong to the owner (spec 007).
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .checks import BY_TYPE, CATALOGUE
from .errors import UsageError
from .models import CheckResult, CheckSpec, CheckStatus, ScanReport
from .scan import ScanOptions, run_scan
from .synth import MIN_DRIFT_ROWS, Fault, shop_tables

log = logging.getLogger(__name__)

R1_CHECKS = tuple(c.type for c in CATALOGUE if c.release == "R1")
OTHER_SEED = 10_000

Key = tuple[str, str, str | None]


@dataclass
class CheckAccuracy:
    """The measures of one check, summed over seeds."""

    check: str
    kind: str
    groups: int = 0
    fault_rows: int = 0
    detected: int = 0
    exact: int = 0
    unexpected: int = 0
    clean_findings: int = 0
    clean_failed_rows: int = 0
    clean_evaluated: int = 0
    baseline_checks: int = 0
    baseline_findings: int = 0
    sampled_groups: int = 0
    sampled_detected: int = 0
    coverage_groups: int = 0
    covered: int = 0


@dataclass
class AccuracyReport:
    seeds: int
    rows: int
    sample_rows: int
    started_at: str
    checks: list[CheckAccuracy] = field(default_factory=list)

    def by_check(self) -> dict[str, CheckAccuracy]:
        return {c.check: c for c in self.checks}

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _key(result: CheckResult) -> Key:
    level = BY_TYPE[result.spec.type].level
    return (result.spec.type, result.spec.asset.name, None if level == "asset" else result.spec.column)


def _fault_key(f: Fault) -> Key:
    level = BY_TYPE[f.check].level
    return (f.check, f.asset, None if level == "asset" else f.column)


def _results(report: ScanReport, kind: str) -> dict[Key, CheckResult]:
    return {_key(r): r for a in report.assets for r in a.checks if BY_TYPE[r.spec.type].kind == kind}


def _locked_baselines(report: ScanReport) -> dict[str, list[CheckSpec]]:
    """The baselines a scan proposed, locked, as an owner approving them would keep them."""
    saved: dict[str, list[CheckSpec]] = {}
    for spec in report.checks:
        if spec.kind == "baseline":
            saved.setdefault(spec.asset.label, []).append(
                spec.model_copy(update={"status": CheckStatus.LOCKED})
            )
    return saved


def validate(seeds: int, rows: int, sample_rows: int) -> None:
    if seeds < 1:
        raise UsageError("--seeds must be at least 1")
    if rows < MIN_DRIFT_ROWS:
        raise UsageError(f"--rows must be at least {MIN_DRIFT_ROWS:,}, so that every baseline check applies")
    if sample_rows < 1:
        raise UsageError("--sample-rows must be at least 1")


def run_benchmark(
    *,
    seeds: int = 20,
    rows: int = 5000,
    sample_rows: int = 500,
    progress: Callable[[str], None] | None = None,
) -> AccuracyReport:
    """Run the benchmark; raises `UsageError` on bad options."""
    validate(seeds, rows, sample_rows)
    say = progress or (lambda _m: None)
    now = datetime.now(UTC).replace(microsecond=0)
    acc = {t: CheckAccuracy(t, BY_TYPE[t].kind) for t in R1_CHECKS}
    report = AccuracyReport(seeds, rows, sample_rows, now.isoformat())
    full = ScanOptions(sample_rows=0)
    with tempfile.TemporaryDirectory(prefix="sahifa-accuracy-") as tmp:
        base = Path(tmp)
        for seed in range(1, seeds + 1):
            faulty = shop_tables(rows=rows, seed=seed, now=now)
            drift = shop_tables(drift=True, rows=rows, seed=seed, now=now)
            dirs = {form: base / f"{form}-{seed}" for form in ("faulty", "clean", "drift", "other")}
            faulty.write(dirs["faulty"])
            shop_tables(clean=True, rows=rows, seed=seed, now=now).write(dirs["clean"])
            drift.write(dirs["drift"])
            shop_tables(clean=True, rows=rows, seed=seed + OTHER_SEED, now=now).write(dirs["other"])

            a = run_scan(str(dirs["faulty"]), full)
            b = run_scan(str(dirs["clean"]), full)
            locked = _locked_baselines(b)
            c = run_scan(str(dirs["drift"]), full, saved=locked)
            d = run_scan(str(dirs["other"]), full, saved=locked)
            # Each seed draws its own sample: the synthetic faults sit at fixed row positions, so
            # one sample seed for all would always see, or always miss, the same rows.
            e = run_scan(str(dirs["faulty"]), ScanOptions(sample_rows=sample_rows, seed=seed))

            _detection(acc, faulty.faults, _results(a, "rule"))
            _detection(acc, drift.faults, _results(c, "baseline"))
            _unexpected(acc, faulty.faults, _results(a, "rule").values())
            _unexpected(acc, drift.faults, _results(c, "baseline").values())
            _clean(acc, b)
            _baseline_alarms(acc, d)
            _sampled(acc, faulty.faults, _results(a, "rule"), e)
            say(f"seed {seed}/{seeds}")
    report.checks = [acc[t] for t in R1_CHECKS]
    return report


def _detection(
    acc: dict[str, CheckAccuracy], faults: Iterable[Fault], results: dict[Key, CheckResult]
) -> None:
    for f in faults:
        m = acc[f.check]
        m.groups += 1
        m.fault_rows += f.rows
        r = results.get(_fault_key(f))
        if r is None:
            log.info("accuracy.missed %s on %s.%s: the check did not apply", f.check, f.asset, f.column)
            continue
        m.detected += int(r.failed > 0)
        m.exact += int(r.failed == f.rows)


def _unexpected(
    acc: dict[str, CheckAccuracy], faults: Iterable[Fault], results: Iterable[CheckResult]
) -> None:
    expected = {_fault_key(f) for f in faults}
    for r in results:
        if r.failed and _key(r) not in expected:
            log.info("accuracy.unexpected %s: %d rows", _key(r), r.failed)
            acc[r.spec.type].unexpected += 1


def _clean(acc: dict[str, CheckAccuracy], report: ScanReport) -> None:
    for r in _results(report, "rule").values():
        m = acc[r.spec.type]
        m.clean_failed_rows += r.failed
        m.clean_evaluated += r.evaluated
    for f in report.findings:
        if f.check_type in acc:
            acc[f.check_type].clean_findings += 1


def _baseline_alarms(acc: dict[str, CheckAccuracy], report: ScanReport) -> None:
    for r in _results(report, "baseline").values():
        if r.spec.status.scores:
            acc[r.spec.type].baseline_checks += 1
    for f in report.findings:
        if f.check_type in acc and BY_TYPE[f.check_type].kind == "baseline":
            acc[f.check_type].baseline_findings += 1


def _sampled(
    acc: dict[str, CheckAccuracy],
    faults: Iterable[Fault],
    full: dict[Key, CheckResult],
    report: ScanReport,
) -> None:
    results = _results(report, "rule")
    sampled_assets = {a.ref.name for a in report.assets if a.sampled}
    for f in faults:
        m = acc[f.check]
        m.sampled_groups += 1
        r, truth = results.get(_fault_key(f)), full.get(_fault_key(f))
        if r is None:
            continue
        m.sampled_detected += int(r.failed > 0)
        if f.asset in sampled_assets and truth is not None:
            m.coverage_groups += 1
            m.covered += int(r.low <= truth.ratio <= r.high)


# --- rendering ------------------------------------------------------------------------------


def _share(k: int, n: int) -> str:
    return "–" if n == 0 else f"{100 * k / n:.0f} %"


def render_markdown(report: AccuracyReport) -> str:
    """The accuracy table, one row per R1 check, as in `docs/checks/catalogue.md`."""
    lines = [
        "| Check | Kind | Fault groups (rows) | Detected | Count exact | Unexpected | "
        "Clean twin: findings, failing rows | Locked baseline on new data: findings | "
        "Sampled: detected | Sampled: interval coverage |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in report.checks:
        clean = (
            "–"
            if m.kind == "baseline"
            else f"{m.clean_findings}, {m.clean_failed_rows:,} of {m.clean_evaluated:,}"
        )
        alarms = f"{m.baseline_findings} of {m.baseline_checks}" if m.kind == "baseline" else "–"
        sampled = "–" if m.kind == "baseline" else _share(m.sampled_detected, m.sampled_groups)
        coverage = "–" if m.kind == "baseline" else _share(m.covered, m.coverage_groups)
        lines.append(
            f"| `{m.check}` | {m.kind} | {m.groups} ({m.fault_rows:,}) | {_share(m.detected, m.groups)} | "
            f"{_share(m.exact, m.groups)} | {m.unexpected} | {clean} | {alarms} | {sampled} | {coverage} |"
        )
    return "\n".join(lines)
