"""A scan with saved checks (spec 007): locked and retired checks change the report."""

from __future__ import annotations

from pathlib import Path

from sahifa_core.models import CheckStatus, Dimension, ScanReport
from sahifa_core.scan import ScanOptions, run_scan


def test_saved_checks_change_the_report(shop: Path, shop_report: ScanReport) -> None:
    specs = {s.id: s for s in shop_report.checks}
    retired = specs["sah.foreign_key:orders:customer_id"].model_copy(update={"status": CheckStatus.RETIRED})
    locked = specs["sah.accepted_values:orders:status"].model_copy(update={"status": CheckStatus.LOCKED})
    report = run_scan(str(shop), ScanOptions(sample_rows=0), saved={"orders": [retired, locked]})

    before = next(a for a in shop_report.assets if a.ref.label == "orders")
    after = next(a for a in report.assets if a.ref.label == "orders")
    results = {r.spec.id: r for r in after.checks}
    assert retired.id not in results and retired.id not in {s.id for s in report.checks}
    assert retired.id not in {f.check_id for f in report.findings}
    assert results[locked.id].spec.status == CheckStatus.LOCKED
    assert locked.id not in {r.spec.id for r in report.proposed}
    assert {s.id: s.status for s in report.checks}[locked.id] == CheckStatus.LOCKED

    # The retired check leaves consistency; the locked baseline now counts toward validity.
    consistency, validity = Dimension.CONSISTENCY, Dimension.VALIDITY
    assert after.score.dimensions[consistency].checks == before.score.dimensions[consistency].checks - 1
    assert after.score.dimensions[consistency].value > before.score.dimensions[consistency].value
    assert after.score.dimensions[validity].checks == before.score.dimensions[validity].checks + 1
    assert report.stats.checks_proposed == shop_report.stats.checks_proposed - 1


def test_report_lists_every_reconciled_check(shop_report: ScanReport) -> None:
    evaluated = {r.spec.id for a in shop_report.assets for r in a.checks}
    assert {s.id for s in shop_report.checks} == evaluated
    assert len(shop_report.checks) == len(evaluated)
    # Evaluation never leaks into the persisted spec (freshness notes the age it measured).
    assert all("age_hours" not in s.params for s in shop_report.checks)
