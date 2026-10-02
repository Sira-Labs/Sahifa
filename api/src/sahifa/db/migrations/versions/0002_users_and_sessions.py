"""Sign-in: users, sessions, login flows (spec 006).

- `users`: a person who signed in through the realm, keyed by the identity (issuer, subject);
  the email is unique and lower case. Access is not stored here: it follows the settings.
- `sessions`: signed-in browsers; the cookie holds a random token and the table only its
  HMAC, with the sign-in method, the IdP session id (back-channel logout) and the ID token
  (logout hint).
- `login_flows`: sign-ins between `/api/auth/login` and the callback (state, nonce, PKCE).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
        sa.UniqueConstraint("email", name="users_email_key"),
        sa.UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("id_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sign_in_method", sa.String(20), nullable=False),
        sa.Column("idp_sid", sa.Text(), nullable=True),
        sa.Column("id_token", sa.Text(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "sign_in_method IN ('google', 'github', 'passkey')", name="ck_sessions_sign_in_method"
        ),
        sa.UniqueConstraint("id_hash", name="sessions_id_hash_key"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_idp_sid", "sessions", ["idp_sid"])
    op.create_table(
        "login_flows",
        sa.Column("id_hash", sa.LargeBinary(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("next", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("login_flows")
    op.drop_index("ix_sessions_idp_sid", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
