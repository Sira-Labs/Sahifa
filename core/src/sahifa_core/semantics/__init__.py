"""Rule packs: validators for semantic types (catalogue check 5, `sah.semantic_format`).

Each validator is a pure function on one string. A column gets a semantic type when at least
80 % of its sampled non-null values pass one validator; validators that would match too much
by accident (country codes, postcodes) also need a name hint in the column name.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .codes import ISO_COUNTRY_2, ISO_COUNTRY_3, ISO_CURRENCY

INFER_SHARE = 0.8

_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,63}$"
)
_URL = re.compile(r"^https?://[^\s/$.?#][^\s]*\.[^\s]+$", re.IGNORECASE)
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_PHONE_STRIP = re.compile(r"[\s().\-/]")
_PHONE = re.compile(r"^\+[1-9][0-9]{7,14}$")

# ISO 13616 IBAN lengths per country (SWIFT IBAN registry).
IBAN_LENGTH: dict[str, int] = {
    "AD": 24,
    "AE": 23,
    "AL": 28,
    "AT": 20,
    "AZ": 28,
    "BA": 20,
    "BE": 16,
    "BG": 22,
    "BH": 22,
    "BI": 27,
    "BR": 29,
    "BY": 28,
    "CH": 21,
    "CR": 22,
    "CY": 28,
    "CZ": 24,
    "DE": 22,
    "DJ": 27,
    "DK": 18,
    "DO": 28,
    "EE": 20,
    "EG": 29,
    "ES": 24,
    "FI": 18,
    "FK": 18,
    "FO": 18,
    "FR": 27,
    "GB": 22,
    "GE": 22,
    "GI": 23,
    "GL": 18,
    "GR": 27,
    "GT": 28,
    "HN": 28,
    "HR": 21,
    "HU": 28,
    "IE": 22,
    "IL": 23,
    "IQ": 23,
    "IS": 26,
    "IT": 27,
    "JO": 30,
    "KW": 30,
    "KZ": 20,
    "LB": 28,
    "LC": 32,
    "LI": 21,
    "LT": 20,
    "LU": 20,
    "LV": 21,
    "LY": 25,
    "MC": 27,
    "MD": 24,
    "ME": 22,
    "MK": 19,
    "MN": 20,
    "MR": 27,
    "MT": 31,
    "MU": 30,
    "NI": 28,
    "NL": 18,
    "NO": 15,
    "OM": 23,
    "PK": 24,
    "PL": 28,
    "PS": 29,
    "PT": 25,
    "QA": 29,
    "RO": 24,
    "RS": 22,
    "RU": 33,
    "SA": 24,
    "SC": 31,
    "SD": 18,
    "SE": 24,
    "SI": 19,
    "SK": 24,
    "SM": 27,
    "SO": 23,
    "ST": 25,
    "SV": 28,
    "TL": 23,
    "TN": 24,
    "TR": 26,
    "UA": 29,
    "VA": 22,
    "VG": 24,
    "XK": 20,
    "YE": 30,
}

# EU VAT identification number formats (after the two-letter prefix; format only, no VIES lookup).
EU_VAT: dict[str, re.Pattern[str]] = {
    k: re.compile(v)
    for k, v in {
        "AT": r"^U[0-9]{8}$",
        "BE": r"^[01][0-9]{9}$",
        "BG": r"^[0-9]{9,10}$",
        "CY": r"^[0-9]{8}[A-Z]$",
        "CZ": r"^[0-9]{8,10}$",
        "DE": r"^[0-9]{9}$",
        "DK": r"^[0-9]{8}$",
        "EE": r"^[0-9]{9}$",
        "EL": r"^[0-9]{9}$",
        "ES": r"^[A-Z0-9][0-9]{7}[A-Z0-9]$",
        "FI": r"^[0-9]{8}$",
        "FR": r"^[A-HJ-NP-Z0-9]{2}[0-9]{9}$",
        "HR": r"^[0-9]{11}$",
        "HU": r"^[0-9]{8}$",
        "IE": r"^([0-9]{7}[A-W][A-I]?|[0-9][A-Z+*][0-9]{5}[A-W])$",
        "IT": r"^[0-9]{11}$",
        "LT": r"^([0-9]{9}|[0-9]{12})$",
        "LU": r"^[0-9]{8}$",
        "LV": r"^[0-9]{11}$",
        "MT": r"^[0-9]{8}$",
        "NL": r"^[0-9]{9}B[0-9]{2}$",
        "PL": r"^[0-9]{10}$",
        "PT": r"^[0-9]{9}$",
        "RO": r"^[0-9]{2,10}$",
        "SE": r"^[0-9]{12}$",
        "SI": r"^[0-9]{8}$",
        "SK": r"^[0-9]{10}$",
        "XI": r"^([0-9]{9}|[0-9]{12}|GD[0-9]{3}|HA[0-9]{3})$",
    }.items()
}


def is_email(v: str) -> bool:
    return len(v) <= 254 and bool(_EMAIL.match(v))


def is_url(v: str) -> bool:
    return len(v) <= 2048 and bool(_URL.match(v))


def is_uuid(v: str) -> bool:
    return bool(_UUID.match(v))


def is_iban(v: str) -> bool:
    s = v.replace(" ", "").upper()
    if len(s) < 15 or len(s) > 34 or not s[:2].isalpha() or not s[2:4].isdigit() or not s.isalnum():
        return False
    expected = IBAN_LENGTH.get(s[:2])
    if expected is not None and len(s) != expected:
        return False
    digits = "".join(str(int(ch, 36)) for ch in s[4:] + s[:4])
    return int(digits) % 97 == 1


def is_eu_vat(v: str) -> bool:
    s = re.sub(r"[\s.\-]", "", v).upper()
    pattern = EU_VAT.get(s[:2])
    return pattern is not None and bool(pattern.match(s[2:]))


def is_iso_country(v: str) -> bool:
    s = v.strip().upper()
    return s in ISO_COUNTRY_2 or s in ISO_COUNTRY_3


def is_iso_currency(v: str) -> bool:
    return v.strip().upper() in ISO_CURRENCY


def is_phone_e164(v: str) -> bool:
    return bool(_PHONE.match(_PHONE_STRIP.sub("", v)))


def is_postcode_de(v: str) -> bool:
    s = v.strip()
    return len(s) == 5 and s.isdigit() and 1001 <= int(s) <= 99998


@dataclass(frozen=True)
class SemanticType:
    name: str
    label: str
    validate: Callable[[str], bool]
    personal: bool = False
    name_hints: tuple[str, ...] = field(default_factory=tuple)
    specificity: int = 1


SEMANTIC_TYPES: tuple[SemanticType, ...] = (
    SemanticType("iban", "IBAN", is_iban, personal=True, specificity=3),
    SemanticType("eu_vat", "EU VAT ID", is_eu_vat, personal=True, specificity=3),
    SemanticType("uuid", "UUID", is_uuid, specificity=3),
    SemanticType("email", "email address", is_email, personal=True, specificity=2),
    SemanticType("url", "URL", is_url, specificity=2),
    SemanticType("phone_e164", "phone number (E.164)", is_phone_e164, personal=True, specificity=2),
    SemanticType(
        "iso_currency",
        "ISO 4217 currency code",
        is_iso_currency,
        name_hints=("currency", "curr", "ccy", "waers", "waehrung"),
    ),
    SemanticType(
        "iso_country",
        "ISO 3166 country code",
        is_iso_country,
        name_hints=("country", "land", "nation", "ctry"),
    ),
    SemanticType(
        "postcode_de",
        "German postcode",
        is_postcode_de,
        name_hints=("zip", "postcode", "postal", "plz", "postleitzahl"),
    ),
)
BY_NAME = {t.name: t for t in SEMANTIC_TYPES}
PERSONAL = frozenset(t.name for t in SEMANTIC_TYPES if t.personal)


def infer(column: str, values: list[tuple[str, int]]) -> tuple[str | None, float | None]:
    """The best semantic type for `(value, count)` pairs, and its share; `(None, None)` if none fits."""
    total = sum(c for _, c in values)
    if total == 0:
        return None, None
    lowered = column.lower()
    best: tuple[str | None, float | None, int] = (None, None, -1)
    for t in SEMANTIC_TYPES:
        if t.name_hints and not any(h in lowered for h in t.name_hints):
            continue
        share = sum(c for v, c in values if t.validate(v.strip())) / total
        if share >= INFER_SHARE and (
            best[1] is None
            or share > best[1] + 1e-9
            or (abs(share - best[1]) <= 1e-9 and t.specificity > best[2])
        ):
            best = (t.name, share, t.specificity)
    return best[0], best[1]


def mask(value: str) -> str:
    """Keep the first and last two characters of a personal value (ADR-0006)."""
    if len(value) <= 4:
        return "•" * len(value)
    return value[:2] + "•" * (len(value) - 4) + value[-2:]
