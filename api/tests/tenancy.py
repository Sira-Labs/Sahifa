"""Workspaces and their rows for the spec 016 tests, written directly through an engine that
sees every workspace (`owner_engine`). `workspace_id` is set only on connections: the triggers
fill it everywhere else."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

# The 11 workspace-owned tables, each with a row in every tree `make_tree` writes.
TABLES = (
    "connections",
    "scans",
    "scan_schedules",
    "assets",
    "columns",
    "checks",
    "check_events",
    "findings",
    "finding_events",
    "finding_occurrences",
    "scores",
)


def sql(engine: Engine, statement: str, **params: Any) -> Any:
    with engine.connect() as conn:
        result = conn.execute(text(statement), params)
        return result.all() if result.returns_rows else None


def make_workspace(owner: Engine, name: str | None = None) -> str:
    wid = str(uuid.uuid4())
    sql(
        owner,
        "INSERT INTO workspaces (id, organisation_id, name) SELECT :id, id, :n FROM organisations",
        id=wid,
        n=name or f"w-{wid[:8]}",
    )
    return wid


def default_workspace(owner: Engine) -> str:
    return str(sql(owner, "SELECT id FROM workspaces WHERE is_default")[0][0])


def user_id(owner: Engine, email: str) -> str:
    return str(sql(owner, "SELECT id FROM users WHERE email = :e", e=email)[0][0])


def add_member(owner: Engine, workspace_id: str, email: str, role: str) -> None:
    sql(
        owner,
        "INSERT INTO memberships (workspace_id, user_id, role) SELECT :w, id, :r FROM users WHERE email = :e"
        " ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = excluded.role",
        w=workspace_id,
        e=email,
        r=role,
    )


def make_tree(owner: Engine, workspace_id: str, *, scan_status: str = "succeeded") -> dict[str, str]:
    """A connection in the workspace with one row in each of the other ten tables."""
    ids = {
        name: str(uuid.uuid4()) for name in ("connection", "scan", "asset", "check", "finding", "schedule")
    }
    statements = (
        "INSERT INTO connections (id, name, kind, workspace_id) VALUES (:connection, :name, 'duckdb', :ws)",
        "INSERT INTO scans (id, connection_id, sample_rows, status) VALUES (:scan, :connection, 0, :status)",
        "INSERT INTO scan_schedules (id, connection_id, cron, updated_by, enabled)"
        " VALUES (:schedule, :connection, '0 2 * * *', 'test', false)",
        "INSERT INTO assets (id, connection_id, namespace, name, kind)"
        " VALUES (:asset, :connection, '', 't', 'table')",
        "INSERT INTO columns (asset_id, name, position, physical_type, logical_type, role)"
        " VALUES (:asset, 'c', 0, 'INTEGER', 'integer', 'measure')",
        "INSERT INTO checks (id, asset_id, key, type, column_name, dimension, severity, kind, origin, status,"
        " params) VALUES (:check, :asset, :key, 'sah.range', 'c', 'accuracy', 'high', 'baseline',"
        " 'generated', 'active', '{\"min\": 1, \"max\": 5}'::jsonb)",
        "INSERT INTO check_events (id, check_id, actor, action, to_status)"
        " VALUES (gen_random_uuid(), :check, 'test', 'approve', 'active')",
        "INSERT INTO findings (id, check_id, status, severity, first_seen_at, last_seen_at)"
        " VALUES (:finding, :check, 'open', 'high', now(), now())",
        "INSERT INTO finding_events (id, finding_id, actor, action, to_status)"
        " VALUES (gen_random_uuid(), :finding, 'test', 'acknowledge', 'acknowledged')",
        "INSERT INTO finding_occurrences (id, scan_id, finding_id, check_type, asset, dimension, severity,"
        " evaluated, failed, ratio, low, high, summary, next_step)"
        " VALUES (gen_random_uuid(), :scan, :finding, 'sah.range', 't', 'accuracy', 'high', 10, 1, 0.9, 0.6,"
        " 0.98, 's', 'n')",
        "INSERT INTO scores (id, scan_id, connection_id, measured_at, checks, dimensions)"
        " VALUES (gen_random_uuid(), :scan, :connection, now(), 1, '{}'::jsonb)",
    )
    with owner.connect() as conn:
        for statement in statements:
            conn.execute(
                text(statement),
                ids
                | {
                    "ws": workspace_id,
                    "name": f"t-{ids['connection']}",
                    "key": f"sah.range:t:c:{ids['check']}",
                    "status": scan_status,
                },
            )
    return ids


def workspaces_of(owner: Engine, connection_id: str) -> dict[str, set[str]]:
    """The workspace ids in each table among the rows of the connection's tree."""
    by_table: dict[str, str] = {
        "connections": "id = :c",
        "scans": "connection_id = :c",
        "scan_schedules": "connection_id = :c",
        "assets": "connection_id = :c",
        "scores": "connection_id = :c",
        "columns": "asset_id IN (SELECT id FROM assets WHERE connection_id = :c)",
        "checks": "asset_id IN (SELECT id FROM assets WHERE connection_id = :c)",
        "check_events": "check_id IN (SELECT k.id FROM checks k JOIN assets a ON a.id = k.asset_id"
        " WHERE a.connection_id = :c)",
        "findings": "check_id IN (SELECT k.id FROM checks k JOIN assets a ON a.id = k.asset_id"
        " WHERE a.connection_id = :c)",
        "finding_events": "finding_id IN (SELECT f.id FROM findings f JOIN checks k ON k.id = f.check_id"
        " JOIN assets a ON a.id = k.asset_id WHERE a.connection_id = :c)",
        "finding_occurrences": "scan_id IN (SELECT id FROM scans WHERE connection_id = :c)",
    }
    return {
        table: {
            str(r[0]) for r in sql(owner, f"SELECT workspace_id FROM {table} WHERE {where}", c=connection_id)
        }
        for table, where in by_table.items()
    }
