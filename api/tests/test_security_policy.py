"""The CI dependency policy script (spec 012): licence expressions, exceptions, audit ignores."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "security_policy.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("security_policy", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["security_policy"] = module
    spec.loader.exec_module(module)
    return module


sp = load()
ALLOWED = {"MIT", "BSD-3-Clause", "Apache-2.0", "MPL-2.0", "PSF-2.0"}


def test_names_and_expressions() -> None:
    assert sp.spdx("MIT License") == "MIT"
    assert sp.spdx("Mozilla Public License 2.0 (MPL 2.0)") == "MPL-2.0"
    assert sp.spdx("(Apache Software License)") == "Apache-2.0"
    assert sp.satisfied("MIT", ALLOWED)
    assert sp.satisfied("(MIT OR GPL-3.0-only)", ALLOWED)
    assert sp.satisfied("Apache-2.0 OR BSD-3-Clause", ALLOWED)
    assert sp.satisfied("MIT AND PSF-2.0", ALLOWED)
    assert sp.satisfied("Mozilla Public License 2.0 (MPL 2.0)", ALLOWED)
    assert not sp.satisfied("MIT AND GPL-3.0-only", ALLOWED)
    assert not sp.satisfied("LGPL-3.0-only", ALLOWED)
    assert not sp.satisfied("UNKNOWN", ALLOWED)
    assert not sp.satisfied("Dual License", ALLOWED)


def test_policy_exceptions_and_skips(tmp_path: Path) -> None:
    path = tmp_path / "licences.toml"
    path.write_text(
        'allowed = ["MIT"]\nskip = ["sahifa-api"]\n'
        '[[exceptions]]\npackage = "psycopg_pool"\nlicence = "LGPL-3.0-only"\nreason = "ADR-0015"\n'
    )
    policy = sp.load_policy(path)
    packages = {
        "fastapi": "MIT",
        "psycopg-pool": "LGPL-3.0-only",
        "sahifa-api": "Apache-2.0",
        "evil": "AGPL-3.0-only",
        "mystery": "UNKNOWN",
    }
    assert sp.check(packages, policy) == ["evil: AGPL-3.0-only", "mystery: UNKNOWN"]
    # An exception covers only the licence it names.
    assert sp.check({"psycopg-pool": "GPL-3.0-only"}, policy) == [
        "psycopg-pool: GPL-3.0-only (excepted only as LGPL-3.0-only)"
    ]
    path.write_text('allowed = ["MIT"]\n[[exceptions]]\npackage = "x"\nlicence = "GPL-3.0-only"\n')
    with pytest.raises(SystemExit):
        sp.load_policy(path)


def test_the_repository_policy_allows_only_the_adr_exceptions() -> None:
    policy = sp.load_policy(ROOT / "security" / "licences.toml")
    assert set(policy.exceptions) == {"psycopg", "psycopg-binary", "psycopg-pool"}
    assert all("ADR-0015" in reason for _licence, reason in policy.exceptions.values())
    assert not {"GPL-3.0-only", "AGPL-3.0-only", "LGPL-3.0-only"} & policy.allowed


def test_pnpm_listing() -> None:
    listing = {
        "MIT": [{"name": "react"}, {"name": "@tanstack/react-query"}],
        "OFL-1.1": [{"name": "@fontsource/figtree"}],
    }
    assert sp.pnpm_packages(listing) == {
        "react": "MIT",
        "@tanstack/react-query": "MIT",
        "@fontsource/figtree": "OFL-1.1",
    }


def test_audit_ignores_need_a_reason_and_expire(tmp_path: Path) -> None:
    path = tmp_path / "ignore.toml"
    future = date.today() + timedelta(days=30)
    past = date.today() - timedelta(days=1)
    path.write_text(
        f'[[ignore]]\nid = "GHSA-aaaa"\nreason = "not reachable"\nexpires = {future.isoformat()}\n'
        f'[[ignore]]\nid = "GHSA-bbbb"\nreason = "old"\nexpires = {past.isoformat()}\n'
        '[[ignore]]\nid = "GHSA-cccc"\n'
    )
    entries, failures = sp.load_ignores(path)
    assert [e.id for e in entries] == ["GHSA-aaaa", "GHSA-bbbb"]
    assert len(failures) == 2 and "expired" in failures[0] and "needs id, reason and expires" in failures[1]
    assert sp.load_ignores(tmp_path / "missing.toml") == ([], [])


def run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str], stdin: object) -> int:
    ignores = tmp_path / "ignore.toml"
    future = (date.today() + timedelta(days=30)).isoformat()
    ignores.write_text(f'[[ignore]]\nid = "PYSEC-1"\nreason = "accepted"\nexpires = {future}\n')
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin)))
    code: int = sp.main(["--ignores", str(ignores), *args])
    return code


def test_audits_fail_on_findings_not_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    accepted = {
        "dependencies": [{"name": "x", "version": "1", "vulns": [{"id": "GHSA-1", "aliases": ["PYSEC-1"]}]}]
    }
    assert run(monkeypatch, tmp_path, ["audit", "pip"], accepted) == 0
    new = {"dependencies": [{"name": "y", "version": "2", "vulns": [{"id": "GHSA-2", "aliases": []}]}]}
    assert run(monkeypatch, tmp_path, ["audit", "pip"], new) == 1
    assert run(monkeypatch, tmp_path, ["audit", "pip"], {"dependencies": []}) == 0

    def advisory(severity: str) -> dict[str, object]:
        return {
            "advisories": {
                "1": {
                    "id": 1,
                    "severity": severity,
                    "module_name": "z",
                    "github_advisory_id": "GHSA-3",
                    "cves": [],
                }
            }
        }

    assert run(monkeypatch, tmp_path, ["audit", "pnpm"], advisory("moderate")) == 0
    assert run(monkeypatch, tmp_path, ["audit", "pnpm"], advisory("high")) == 1


def test_unusable_input_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    with pytest.raises(SystemExit) as stop:
        sp.main(["--ignores", str(tmp_path / "x.toml"), "audit", "pip"])
    assert stop.value.code == 2
