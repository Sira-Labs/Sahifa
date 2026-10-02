from __future__ import annotations

import json

from sahifa_core.cli import main


def test_scan_json(shop, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["scan", str(shop), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["findings"] and report["score"]["overall"] is not None


def test_usage_error(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["scan", str(tmp_path / "missing")]) == 2


def test_checks_lists_catalogue(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["checks"]) == 0
    assert "sah.foreign_key" in capsys.readouterr().out
