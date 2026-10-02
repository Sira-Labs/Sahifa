"""Reconciling saved and generated checks (spec 007): one test per row of the table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sahifa_core.checks.lifecycle import reconcile
from sahifa_core.models import AssetRef, CheckSpec, CheckStatus, Dimension, Severity, label_of
from sahifa_core.scan import ScanOptions, run_scan

ORDERS = AssetRef(name="orders", kind="file")


def spec(
    type_: str = "sah.range",
    column: str = "amount",
    status: CheckStatus = CheckStatus.PROPOSED,
    origin: str = "generated",
    **params: Any,
) -> CheckSpec:
    return CheckSpec(
        id=f"{type_}:{ORDERS.label}:{column}",
        type=type_,
        asset=ORDERS,
        column=column,
        params=params,
        dimension=Dimension.ACCURACY,
        severity=Severity.HIGH,
        kind="manual" if origin == "manual" else "baseline",
        status=status,
        origin=origin,  # type: ignore[arg-type]
    )


def test_new_generated_check_keeps_default_status() -> None:
    g = spec(min=1, max=5)
    assert reconcile([g], []) == [g]


def test_active_generated_takes_new_params() -> None:
    saved = spec(status=CheckStatus.ACTIVE, min=1, max=5)
    [out] = reconcile([spec(min=1, max=9)], [saved])
    assert out.status == CheckStatus.ACTIVE and out.params == {"min": 1, "max": 9}


def test_proposed_stays_proposed_with_new_params() -> None:
    saved = spec(status=CheckStatus.PROPOSED, min=1, max=5)
    [out] = reconcile([spec(status=CheckStatus.PROPOSED, min=0, max=5)], [saved])
    assert out.status == CheckStatus.PROPOSED and out.params == {"min": 0, "max": 5}


def test_active_not_generated_is_dropped() -> None:
    saved = [spec(status=CheckStatus.ACTIVE, min=1, max=5), spec(column="gone", status=CheckStatus.PROPOSED)]
    assert reconcile([], saved) == []


def test_locked_keeps_saved_params() -> None:
    saved = spec(status=CheckStatus.LOCKED, min=1, max=5)
    assert reconcile([spec(min=1, max=9)], [saved]) == [saved]
    assert reconcile([], [saved]) == [saved]


def test_locked_with_missing_column_is_unevaluated(shop: Path) -> None:
    locked = spec(column="discount", status=CheckStatus.LOCKED, min=0, max=10)
    assert reconcile([], [locked]) == [locked]
    report = run_scan(str(shop), ScanOptions(sample_rows=0), saved={"orders": [locked]})
    orders = next(a for a in report.assets if a.ref.label == "orders")
    assert [(u.spec.id, u.reason) for u in orders.unevaluated] == [(locked.id, "column_missing")]
    assert locked.id not in {r.spec.id for r in orders.checks}
    assert locked in report.checks


def test_retired_is_never_evaluated_or_recreated(shop: Path) -> None:
    retired = spec(status=CheckStatus.RETIRED, min=1, max=5)
    assert reconcile([spec(min=1, max=9)], [retired]) == []
    assert reconcile([], [retired]) == []
    key = "sah.accepted_values:orders:status"
    report = run_scan(
        str(shop),
        ScanOptions(sample_rows=0),
        saved={"orders": [spec("sah.accepted_values", "status", CheckStatus.RETIRED, values=["paid"])]},
    )
    assert key not in {s.id for s in report.checks}
    assert key not in {r.spec.id for a in report.assets for r in a.checks}


def test_manual_is_kept() -> None:
    manual = spec(column="amount", status=CheckStatus.ACTIVE, origin="manual", min=0, max=1)
    assert reconcile([spec(min=1, max=9)], [manual]) == [manual]
    assert reconcile([], [manual]) == [manual]
    retired = manual.model_copy(update={"status": CheckStatus.RETIRED})
    assert reconcile([], [retired]) == []


def test_labels_are_lossless() -> None:
    """Two assets whose dotted parts join to the same text keep distinct labels."""
    a, b = AssetRef(namespace="a.b", name="c"), AssetRef(namespace="a", name="b.c")
    assert a.label == '"a.b".c' and b.label == 'a."b.c"' and a.label != b.label
    assert AssetRef(name="orders").label == "orders"
    assert AssetRef(namespace="public", name="orders").label == "public.orders"
    assert label_of("", 'say "hi"') == '"say ""hi"""'
