"""Workspaces, memberships and roles with row-level security (spec 016).

- `organisations` (one row per install in R2), `workspaces` (one marked `is_default`, named
  `Default`), `memberships` (workspace, user, role).
- `workspace_id` on every workspace-owned table, backfilled with `Default`. On every table but
  `connections` a `BEFORE INSERT` trigger copies it from the parent row, so no insert path can
  leave it empty or wrong.
- Row-level security on those tables: a row is visible when `sahifa.system` is `on` or its
  workspace is in `sahifa.workspaces`, both set per transaction by the API (`db/__init__.py`).
  With neither set, nothing is visible. `FORCE` binds the table owner too.
- The role `sahifa_app` (no login), which every API session switches to with `SET LOCAL ROLE`:
  a superuser, which the Postgres image makes of `POSTGRES_USER`, bypasses row-level security
  even with `FORCE`, a role switched to does not. Created only when the migrating login may
  create roles; otherwise `FORCE` alone binds a non-superuser owner, and the API refuses to start
  in prod as a superuser without the role (`settings.py`).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# (table, parent table, column naming the parent); `connections` has no parent.
OWNED: tuple[tuple[str, str | None, str | None], ...] = (
    ("connections", None, None),
    ("scans", "connections", "connection_id"),
    ("scan_schedules", "connections", "connection_id"),
    ("assets", "connections", "connection_id"),
    ("scores", "connections", "connection_id"),
    ("columns", "assets", "asset_id"),
    ("checks", "assets", "asset_id"),
    ("check_events", "checks", "check_id"),
    ("findings", "checks", "check_id"),
    ("finding_events", "findings", "finding_id"),
    ("finding_occurrences", "scans", "scan_id"),
)

VISIBLE = """
CREATE FUNCTION sahifa_visible(ws uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT coalesce(current_setting('sahifa.system', true), '') = 'on'
      OR ws = ANY (coalesce(string_to_array(nullif(current_setting('sahifa.workspaces', true), ''), ','),
                            '{}')::uuid[])
$$
"""

FILL = """
CREATE FUNCTION sahifa_fill_workspace() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- TG_ARGV: parent table, column naming the parent. Read under the inserting session's
  -- row-level security: a parent in a workspace it cannot see leaves NULL, which fails NOT NULL.
  EXECUTE format('SELECT workspace_id FROM %I WHERE id = $1', TG_ARGV[0])
    INTO NEW.workspace_id
    USING (to_jsonb(NEW) ->> TG_ARGV[1])::uuid;
  RETURN NEW;
END
$$
"""

# Created when the migrating login may create roles. The table owner grants the privileges in
# any case, then joins the role; a login that may neither create nor join it is warned, not
# failed, and row-level security then relies on FORCE (a non-superuser owner).
APP_ROLE_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sahifa_app') THEN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND (rolsuper OR rolcreaterole)) THEN
      CREATE ROLE sahifa_app NOLOGIN;
    ELSE
      RAISE NOTICE 'sahifa: % may not create roles; row-level security relies on FORCE', current_user;
      RETURN;
    END IF;
  END IF;
  GRANT USAGE ON SCHEMA public TO sahifa_app;
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sahifa_app;
  GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sahifa_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sahifa_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO sahifa_app;
  IF NOT pg_has_role(current_user, 'sahifa_app', 'MEMBER') THEN
    BEGIN
      EXECUTE format('GRANT sahifa_app TO %I', current_user);
    EXCEPTION WHEN insufficient_privilege THEN
      RAISE NOTICE 'sahifa: % may not join sahifa_app; row-level security relies on FORCE', current_user;
    END;
  END IF;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_workspaces_org_name", "workspaces", ["organisation_id", sa.text("lower(name)")], unique=True
    )
    op.create_index(
        "uq_workspaces_default",
        "workspaces",
        ["organisation_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "memberships",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("role IN ('viewer', 'editor', 'admin')", name="ck_memberships_role"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.execute(
        "INSERT INTO organisations (id, name) VALUES (gen_random_uuid(), 'Sahifa');"
        "INSERT INTO workspaces (id, organisation_id, name, is_default) "
        "SELECT gen_random_uuid(), id, 'Default', true FROM organisations"
    )

    # Backfill before row-level security is on: a non-superuser owner would see no rows after.
    for table, _, _ in OWNED:
        op.add_column(table, sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(f"UPDATE {table} SET workspace_id = (SELECT id FROM workspaces WHERE is_default)")  # noqa: S608
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"], ondelete="RESTRICT"
        )
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])

    op.execute(VISIBLE)
    op.execute(FILL)
    for table, parent, column in OWNED:
        if parent is not None:
            op.execute(
                f"CREATE TRIGGER trg_{table}_workspace BEFORE INSERT ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION sahifa_fill_workspace('{parent}', '{column}')"
            )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY workspace_isolation ON {table} "
            "USING (sahifa_visible(workspace_id)) WITH CHECK (sahifa_visible(workspace_id))"
        )
    op.execute(APP_ROLE_SQL)


def downgrade() -> None:
    for table, parent, _ in reversed(OWNED):
        op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        if parent is not None:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_workspace ON {table}")
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_constraint(f"fk_{table}_workspace_id", table, type_="foreignkey")
        op.drop_column(table, "workspace_id")
    op.execute("DROP FUNCTION IF EXISTS sahifa_fill_workspace()")
    op.execute("DROP FUNCTION IF EXISTS sahifa_visible(uuid)")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("uq_workspaces_default", table_name="workspaces")
    op.drop_index("uq_workspaces_org_name", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("organisations")
    # The role `sahifa_app` and its grants stay: harmless without the policies, and dropping a
    # role another database may use is not this migration's call.
