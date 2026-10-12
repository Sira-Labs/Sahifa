"""What a source's login or process may do (spec 021).

The Postgres tests need SAHIFA_TEST_SOURCE_URL with a login that may create roles; each test
makes its own roles and drops them afterwards.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from sahifa_core.cli import main
from sahifa_core.connectors import duckdb as duckdb_module
from sahifa_core.connectors import open_source
from sahifa_core.connectors.postgres import PostgresConnector
from sahifa_core.errors import SourceError
from sahifa_core.models import SourceAccess
from sahifa_core.scan import ScanOptions, run_scan

URL = os.environ.get("SAHIFA_TEST_SOURCE_URL")
needs_pg = pytest.mark.skipif(not URL, reason="SAHIFA_TEST_SOURCE_URL not set")
SCHEMA = "sahifa_access"
OTHER = "sahifa_access_other"


def as_login(name: str, password: str, schemas: str = SCHEMA) -> str:
    """The test database's URL with another login and Sahifa's `schemas=` parameter."""
    assert URL
    parts = urlsplit(URL)
    netloc = f"{name}:{password}@{parts.hostname}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, f"schemas={schemas}", ""))


class Roles:
    """Login roles made for one test, dropped with everything granted to them."""

    def __init__(self, con: psycopg.Connection) -> None:  # type: ignore[type-arg]
        self.con = con
        self.made: list[str] = []

    def login(self, *grants: str, attributes: str = "") -> str:
        name = f"sahifa_acc_{uuid.uuid4().hex[:8]}"
        password = uuid.uuid4().hex
        self.con.execute(f"CREATE ROLE {name} LOGIN PASSWORD '{password}' {attributes}")
        self.made.append(name)
        # Since Postgres 16 a CREATEROLE login is not a member of the roles it makes; joining
        # lets it hand a table over and drop what the role owns.
        self.con.execute(f"GRANT {name} TO CURRENT_USER")
        database = urlsplit(URL or "").path.lstrip("/")
        self.con.execute(f'GRANT CONNECT ON DATABASE "{database}" TO {name}')
        self.con.execute(f"GRANT USAGE ON SCHEMA {SCHEMA}, {OTHER} TO {name}")
        self.con.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {name}")
        for grant in grants:
            self.con.execute(grant.format(role=name))
        return as_login(name, password)


@pytest.fixture
def roles() -> Iterator[Roles]:
    assert URL
    with psycopg.connect(URL, autocommit=True) as con:
        for schema in (SCHEMA, OTHER):
            con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            con.execute(f"CREATE SCHEMA {schema}")
        con.execute(f"CREATE TABLE {SCHEMA}.orders (id int, amount numeric)")
        con.execute(f"CREATE TABLE {SCHEMA}.customers (id int, email text)")
        con.execute(f"CREATE TABLE {OTHER}.ledger (id int)")
        made = Roles(con)
        try:
            yield made
        finally:
            for name in made.made:
                con.execute(f"DROP OWNED BY {name}")
                con.execute(f"DROP ROLE {name}")
            for schema in (SCHEMA, OTHER):
                con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def report(url: str) -> SourceAccess:
    with open_source(url) as src:
        return src.access_report()


@needs_pg
def test_the_documented_read_only_login(roles: Roles) -> None:
    got = report(roles.login())
    assert got.verdict == "read_only", got
    assert (got.readable, got.unreadable, got.writable, got.advice) == (2, 0, [], None)


@needs_pg
def test_a_write_grant_on_one_table(roles: Roles) -> None:
    got = report(roles.login(f"GRANT INSERT ON {SCHEMA}.orders TO {{role}}"))
    assert got.verdict == "can_write"
    assert (got.writable, got.writable_count) == ([f"{SCHEMA}.orders"], 1)
    assert got.advice and "1 table" in got.advice and "read-only-login" in got.advice


@needs_pg
def test_create_on_a_schema(roles: Roles) -> None:
    got = report(roles.login(f"GRANT CREATE ON SCHEMA {SCHEMA} TO {{role}}"))
    assert got.verdict == "can_write" and got.can_create_in == [f"schema {SCHEMA}"]


@needs_pg
def test_owning_a_table(roles: Roles) -> None:
    # A new owner needs CREATE on the schema for the hand-over; it is taken back afterwards.
    url = roles.login(
        f"GRANT CREATE ON SCHEMA {SCHEMA} TO {{role}}",
        f"ALTER TABLE {SCHEMA}.customers OWNER TO {{role}}",
        f"REVOKE CREATE ON SCHEMA {SCHEMA} FROM {{role}}",
    )
    got = report(url)
    assert got.verdict == "can_write" and got.writable == [f"{SCHEMA}.customers"]


@needs_pg
def test_a_role_flag(roles: Roles) -> None:
    got = report(roles.login(attributes="CREATEROLE"))
    assert got.verdict == "can_write" and got.role_flags == ["createrole"]


@needs_pg
def test_tables_outside_the_scanned_schemas_do_not_count(roles: Roles) -> None:
    url = roles.login(f"GRANT INSERT ON {OTHER}.ledger TO {{role}}")
    assert report(url).verdict == "read_only"
    wider = url.replace(f"schemas={SCHEMA}", f"schemas={SCHEMA},{OTHER}")
    got = report(wider)
    assert got.verdict == "can_write" and got.writable == [f"{OTHER}.ledger"]
    # ledger is not granted SELECT: counted, so the person knows a scan skips it.
    assert (got.readable, got.unreadable) == (2, 1)


@needs_pg
def test_the_scan_records_the_verdict(roles: Roles) -> None:
    url = roles.login(f"GRANT UPDATE ON {SCHEMA}.orders TO {{role}}")
    scanned = run_scan(url, ScanOptions(sample_rows=0))
    assert scanned.source_access and scanned.source_access.verdict == "can_write"
    assert run_scan(url, ScanOptions(sample_rows=0, access=False)).source_access is None


def test_a_failing_check_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    con = PostgresConnector.__new__(PostgresConnector)
    con.schemas = []

    def refuse(sql: str, params: list[object]) -> list[tuple[object, ...]]:
        raise SourceError("permission denied for table pg_roles")

    monkeypatch.setattr(con, "_params", refuse)
    got = con.access_report()
    assert got.verdict == "unknown" and got.reason and "permission denied" in got.reason


def test_writable_files_and_folder(shop: Path) -> None:
    got = report(str(shop))
    assert got.verdict == "can_write" and got.readable >= 6
    assert f"{shop}/" in got.writable and got.advice and ":ro" in got.advice


@pytest.mark.skipif(os.geteuid() == 0, reason="root may write regardless of the permission bits")
def test_read_only_files(tmp_path: Path) -> None:
    folder = tmp_path / "exports"
    folder.mkdir()
    (folder / "orders.csv").write_text("id,amount\n1,10\n")
    (folder / "orders.csv").chmod(0o444)
    folder.chmod(0o555)
    try:
        got = report(str(folder))
        assert got.verdict == "read_only" and (got.readable, got.writable) == (1, [])
    finally:
        folder.chmod(0o755)


def test_cli_exit_codes(
    shop: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["access", str(shop)]) == 3
    assert "could write" in capsys.readouterr().out
    monkeypatch.setattr(duckdb_module, "_writable", lambda path: False)
    assert main(["access", str(shop), "--json"]) == 0
    assert '"verdict":"read_only"' in capsys.readouterr().out

    def unknown(self: object) -> SourceAccess:
        return SourceAccess(verdict="unknown", reason="no idea")

    monkeypatch.setattr(duckdb_module.DuckDBConnector, "access_report", unknown)
    assert main(["access", str(shop)]) == 1
    assert main(["access", "/no/such/folder"]) == 2
