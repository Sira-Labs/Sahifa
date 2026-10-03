"""Findings across scans: occurrences, findings and their events (spec 009).

- `findings` (one row per failing check per scan, migration 0001) is renamed
  `finding_occurrences`, with its indexes and constraints, and gains `finding_id`. Rows from
  before this migration keep `finding_id` null: their scans had no persisted checks.
- `findings` (new): one row per check that failed, at most one not resolved per check (partial
  unique index); `version` guards changes by people and the scanner.
- `finding_events`: who changed what, with an optional note of at most 1000 characters;
  `actor` (email, `scanner`, `dev` or `proxy`) outlives the user.

The downgrade drops the new tables and renames the occurrences back, keeping their rows.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# (old, new) names of the renamed table's indexes and constraints.
RENAMED_INDEXES = (
    ("ix_findings_scan_severity", "ix_finding_occurrences_scan_severity"),
    ("ix_findings_check_type", "ix_finding_occurrences_check_type"),
)
RENAMED_CONSTRAINTS = (
    ("findings_pkey", "finding_occurrences_pkey"),
    ("findings_scan_id_fkey", "finding_occurrences_scan_id_fkey"),
)


def _rename(table: str, pairs: tuple[tuple[str, str], ...], *, constraints: bool, back: bool) -> None:
    for old, new in pairs:
        a, b = (new, old) if back else (old, new)
        if constraints:
            op.execute(sa.text(f'ALTER TABLE {table} RENAME CONSTRAINT "{a}" TO "{b}"'))
        else:
            op.execute(sa.text(f'ALTER INDEX "{a}" RENAME TO "{b}"'))


def upgrade() -> None:
    op.rename_table("findings", "finding_occurrences")
    _rename("finding_occurrences", RENAMED_INDEXES, constraints=False, back=False)
    _rename("finding_occurrences", RENAMED_CONSTRAINTS, constraints=True, back=False)

    op.create_table(
        "findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "check_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("checks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "first_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'muted')", name="ck_findings_status"
        ),
    )
    op.create_index(
        "uq_findings_check_unresolved",
        "findings",
        ["check_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'resolved'"),
    )
    op.create_index("ix_findings_check_id", "findings", ["check_id"])
    op.create_index("ix_findings_status_severity", "findings", ["status", "severity"])

    op.create_table(
        "finding_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "action IN ('opened', 'recurred', 'auto_resolved', 'reopened', 'unmuted', 'acknowledge', "
            "'resolve', 'mute', 'unmute', 'reopen')",
            name="ck_finding_events_action",
        ),
        sa.CheckConstraint("char_length(note) <= 1000", name="ck_finding_events_note_length"),
    )
    op.create_index("ix_finding_events_finding_at", "finding_events", ["finding_id", "at"])

    op.add_column(
        "finding_occurrences",
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.id", ondelete="SET NULL", name="finding_occurrences_finding_id_fkey"),
            nullable=True,
        ),
    )
    op.create_index("ix_finding_occurrences_finding_scan", "finding_occurrences", ["finding_id", "scan_id"])


def downgrade() -> None:
    op.drop_index("ix_finding_occurrences_finding_scan", table_name="finding_occurrences")
    op.drop_column("finding_occurrences", "finding_id")
    op.drop_index("ix_finding_events_finding_at", table_name="finding_events")
    op.drop_table("finding_events")
    op.drop_index("ix_findings_status_severity", table_name="findings")
    op.drop_index("ix_findings_check_id", table_name="findings")
    op.drop_index("uq_findings_check_unresolved", table_name="findings")
    op.drop_table("findings")
    _rename("finding_occurrences", RENAMED_CONSTRAINTS, constraints=True, back=True)
    _rename("finding_occurrences", RENAMED_INDEXES, constraints=False, back=True)
    op.rename_table("finding_occurrences", "findings")
