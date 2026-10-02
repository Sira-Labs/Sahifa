from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sahifa_core.scan import ScanOptions, run_scan
from sahifa_core.synth import write_shop

NOW = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


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
    return run_scan(str(shop), ScanOptions(sample_rows=0))


@pytest.fixture(scope="session")
def clean_report(clean_shop: Path):  # type: ignore[no-untyped-def]
    return run_scan(str(clean_shop), ScanOptions(sample_rows=0))
