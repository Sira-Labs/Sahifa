"""Every R1 rule check fires on the faulty shop and stays silent on the clean twin (spec 003)."""

from __future__ import annotations

import pytest

from sahifa_core.checks import CATALOGUE

RULES = sorted(c.type for c in CATALOGUE if c.kind == "rule")
BASELINES = sorted(c.type for c in CATALOGUE if c.kind == "baseline")


@pytest.mark.parametrize("check", RULES)
def test_rule_fires_on_faulty_shop(shop_report, check):  # type: ignore[no-untyped-def]
    assert any(f.check_type == check for f in shop_report.findings), f"{check} found nothing"


def test_clean_shop_has_no_findings(clean_report):  # type: ignore[no-untyped-def]
    assert clean_report.findings == []
    assert clean_report.score.overall == 100.0


@pytest.mark.parametrize("check", BASELINES)
def test_baselines_are_proposed_not_scored(shop_report, check):  # type: ignore[no-untyped-def]
    proposed = [r for r in shop_report.proposed if r.spec.type == check]
    assert proposed, f"{check} was never proposed"
    assert all(r.spec.status.value == "proposed" for r in proposed)
    assert not any(f.check_type == check for f in shop_report.findings)


def test_findings_explain_themselves(shop_report):  # type: ignore[no-untyped-def]
    for f in shop_report.findings:
        assert f.summary and f.next_step
        assert f.failed > 0 and f.evaluated >= f.failed
        if f.check_type not in ("sah.row_count", "sah.not_null", "sah.duplicate_rows"):
            assert f.examples, f"{f.check_type} has no examples"


def test_personal_examples_are_masked(shop_report):  # type: ignore[no-untyped-def]
    iban = next(
        f for f in shop_report.findings if f.check_type == "sah.semantic_format" and f.column == "iban"
    )
    assert all(e.masked and "•" in (e.value or "") for e in iban.examples)
