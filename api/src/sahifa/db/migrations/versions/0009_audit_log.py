"""Audit log of people's changes (spec 018).

- `audit_events`: one row per change a person made, in a workspace, with before and after.
- Under row-level security like the other workspace-owned tables (migration 0008).
- Append-only: a trigger refuses `UPDATE` and `DELETE` for every role, the owner included.
  Two exceptions:
  - the `SET NULL` of a deleted user's id, which changes nothing else;
  - a deletion the caller marks with the transaction-local setting `sahifa.audit_purge` (the
    cascade when a workspace is deleted, S4-3).

  `sahifa_app` also loses `UPDATE` and `DELETE` on the table.
- Backfill: the people's events of `check_events` and `finding_events`.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APPEND_ONLY = """
CREATE FUNCTION sahifa_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF coalesce(current_setting('sahifa.audit_purge', true), '') = 'on' THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  -- A deleted user: ON DELETE SET NULL clears user_id and nothing else.
  IF TG_OP = 'UPDATE' AND NEW.user_id IS NULL AND OLD.user_id IS NOT NULL
     AND to_jsonb(NEW) - 'user_id' = to_jsonb(OLD) - 'user_id' THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'insufficient_privilege';
END
$$
"""

REVOKE = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sahifa_app') THEN
    REVOKE UPDATE, DELETE ON audit_events FROM sahifa_app;
  END IF;
END
$$
"""

# Summaries as the API writes them: a verb, the check type, the asset's label (`namespace.name`, or
# the name; without the core's quoting of dotted names) and the check's column or columns.
BACKFILL_CHECKS = """
INSERT INTO audit_events (id, at, workspace_id, user_id, actor, action, object_type, object_id, summary,
                          before, after)
SELECT gen_random_uuid(), e.at, e.workspace_id, e.user_id, e.actor, 'check.' || e.action, 'check', e.check_id,
       CASE e.action
         WHEN 'approve' THEN 'Approved' WHEN 'reject' THEN 'Rejected' WHEN 'lock' THEN 'Locked'
         WHEN 'unlock' THEN 'Unlocked' WHEN 'retire' THEN 'Retired' WHEN 'restore' THEN 'Restored'
         WHEN 'acknowledge' THEN 'Acknowledged' WHEN 'resolve' THEN 'Resolved' WHEN 'mute' THEN 'Muted'
         WHEN 'unmute' THEN 'Unmuted' WHEN 'reopen' THEN 'Reopened' ELSE e.action END
       || ' ' || c.type || ' on '
       || CASE WHEN a.namespace = '' THEN a.name ELSE a.namespace || '.' || a.name END
         || coalesce('.' || coalesce(c.column_name,
                     (SELECT string_agg(x, ', ') FROM jsonb_array_elements_text(c.columns) AS x)), ''),
       jsonb_build_object('status', e.from_status), jsonb_build_object('status', e.to_status)
FROM check_events e JOIN checks c ON c.id = e.check_id JOIN assets a ON a.id = c.asset_id
WHERE e.actor <> 'scanner'
"""

BACKFILL_FINDINGS = """
INSERT INTO audit_events (id, at, workspace_id, user_id, actor, action, object_type, object_id, summary,
                          before, after)
SELECT gen_random_uuid(), e.at, e.workspace_id, e.user_id, e.actor, 'finding.' || e.action, 'finding',
       e.finding_id,
       CASE e.action
         WHEN 'approve' THEN 'Approved' WHEN 'reject' THEN 'Rejected' WHEN 'lock' THEN 'Locked'
         WHEN 'unlock' THEN 'Unlocked' WHEN 'retire' THEN 'Retired' WHEN 'restore' THEN 'Restored'
         WHEN 'acknowledge' THEN 'Acknowledged' WHEN 'resolve' THEN 'Resolved' WHEN 'mute' THEN 'Muted'
         WHEN 'unmute' THEN 'Unmuted' WHEN 'reopen' THEN 'Reopened' ELSE e.action END
       || ' finding of ' || c.type || ' on '
       || CASE WHEN a.namespace = '' THEN a.name ELSE a.namespace || '.' || a.name END
         || coalesce('.' || coalesce(c.column_name,
                     (SELECT string_agg(x, ', ') FROM jsonb_array_elements_text(c.columns) AS x)), ''),
       jsonb_build_object('status', e.from_status),
       jsonb_strip_nulls(jsonb_build_object('status', e.to_status, 'note', e.note))
FROM finding_events e JOIN findings f ON f.id = e.finding_id JOIN checks c ON c.id = f.check_id
     JOIN assets a ON a.id = c.asset_id
WHERE e.action IN ('acknowledge', 'resolve', 'mute', 'unmute', 'reopen')
"""


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE", name="fk_audit_events_workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("object_type", sa.String(20), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_audit_events_workspace_at", "audit_events", ["workspace_id", sa.text("at DESC")])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.execute(APPEND_ONLY)
    op.execute(
        "CREATE TRIGGER trg_audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION sahifa_audit_append_only()"
    )
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON audit_events "
        "USING (sahifa_visible(workspace_id)) WITH CHECK (sahifa_visible(workspace_id))"
    )
    op.execute(REVOKE)
    # The event tables are under row-level security: read them as the system.
    op.execute("SELECT set_config('sahifa.system', 'on', true)")
    op.execute(BACKFILL_CHECKS)
    op.execute(BACKFILL_FINDINGS)


def downgrade() -> None:
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION IF EXISTS sahifa_audit_append_only()")
