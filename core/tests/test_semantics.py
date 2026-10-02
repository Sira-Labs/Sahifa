from __future__ import annotations

import pytest

from sahifa_core import semantics as s
from sahifa_core.profile import pattern_class, pattern_regex


@pytest.mark.parametrize(
    "v,ok",
    [
        ("DE89370400440532013000", True),
        ("DE89 3704 0044 0532 0130 00", True),
        ("DE89370400440532013001", False),
        ("XX00", False),
    ],
)
def test_iban(v: str, ok: bool) -> None:
    assert s.is_iban(v) is ok


@pytest.mark.parametrize(
    "v,ok",
    [
        ("DE123456789", True),
        ("ATU12345678", True),
        ("NL123456789B01", True),
        ("DE12345", False),
        ("US123456789", False),
    ],
)
def test_eu_vat(v: str, ok: bool) -> None:
    assert s.is_eu_vat(v) is ok


def test_basic_validators() -> None:
    assert s.is_email("anna@example.org") and not s.is_email("anna@")
    assert s.is_phone_e164("+49 30 1234567") and not s.is_phone_e164("030 1234567")
    assert s.is_iso_country("DE") and s.is_iso_country("deu") and not s.is_iso_country("XX")
    assert s.is_iso_currency("EUR") and not s.is_iso_currency("EURO")
    assert s.is_postcode_de("10115") and not s.is_postcode_de("00999")
    assert s.is_uuid("123e4567-e89b-12d3-a456-426614174000")


def test_infer_needs_name_hint_for_codes() -> None:
    values = [("DE", 50), ("AT", 30), ("FR", 20)]
    assert s.infer("country", values)[0] == "iso_country"
    assert s.infer("status", values)[0] is None


def test_mask() -> None:
    assert s.mask("DE89370400440532013000") == "DE" + "•" * 18 + "00"
    assert s.mask("abc") == "•••"


def test_patterns() -> None:
    assert pattern_class("SKU-00012") == "AAA-9{5+}"
    assert pattern_regex("AAA-9{5+}", "[A-Za-z]") == "[A-Za-z][A-Za-z][A-Za-z]\\-[0-9]{5,}"
