from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sahifa_core.scan import ScanOptions, run_scan
from sahifa_core.synth import write_shop

# The shops are written for this moment and scanned at it: a scan on the real clock stopped
# finding the shop's date "40 days ahead" once that day had passed.
NOW = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def shop_now() -> datetime:
    """The moment the shop fixtures were written for; pass it as `ScanOptions.now`."""
    return NOW


@pytest.fixture(scope="session")
def shop(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("shop")
    write_shop(d, rows=5000, now=NOW)
    return d


@pytest.fixture(scope="session")
def clean_shop(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("clean")
    write_shop(d, rows=5000, clean=True, now=NOW)
    return d


@pytest.fixture(scope="session")
def shop_report(shop: Path):  # type: ignore[no-untyped-def]
    return run_scan(str(shop), ScanOptions(sample_rows=0, now=NOW))


@pytest.fixture(scope="session")
def clean_report(clean_shop: Path):  # type: ignore[no-untyped-def]
    return run_scan(str(clean_shop), ScanOptions(sample_rows=0, now=NOW))
