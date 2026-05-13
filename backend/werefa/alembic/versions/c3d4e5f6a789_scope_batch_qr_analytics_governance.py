"""QR invites, kiosk batch, demand analytics, KYC docs, auth depth, notifications.

Revision ID: c3d4e5f6a789
Revises: b1c2d3e4f567
Create Date: 2026-05-11

"""

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a789"
down_revision = "b1c2d3e4f567"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_notification_channel", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_channel",
        "notification",
        "channel IN ('websocket','email','logger','push','sms')",
    )

    op.add_column(
        "notification",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("user", sa.Column("is_suspended", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("user", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user", sa.Column("suspended_reason", sa.String(length=500), nullable=True))
    op.add_column("user", sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("user", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("user", "is_suspended", server_default=None)
    op.alter_column("user", "failed_login_count", server_default=None)

    op.add_column(
        "provider",
        sa.Column("last_rejection_reason", sa.String(length=1000), nullable=True),
    )

    op.create_table(
        "join_invite",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("service_item_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["service_item_id"], ["service_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_join_invite_token"), "join_invite", ["token"], unique=True)

    op.create_table(
        "kiosk_sync_batch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_item_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_item_id"],
            ["service_item.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "service_item_id",
            "idempotency_key",
            name="uq_kiosk_sync_batch_service_idem",
        ),
    )

    op.create_table(
        "demand_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=True),
        sa.Column("service_item_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("client_ref", sa.String(length=120), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["service_item_id"],
            ["service_item.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_demand_event_type_created",
        "demand_event",
        ["event_type", "created_at"],
        unique=False,
    )

    op.create_table(
        "provider_document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("storage_relpath", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["user.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_document_provider_id"),
        "provider_document",
        ["provider_id"],
        unique=False,
    )

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_audit_log_created",
        "admin_audit_log",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "email_otp_challenge",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_otp_challenge_email"),
        "email_otp_challenge",
        ["email"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_email_otp_challenge_email"), table_name="email_otp_challenge")
    op.drop_table("email_otp_challenge")
    op.drop_index("ix_admin_audit_log_created", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
    op.drop_index(op.f("ix_provider_document_provider_id"), table_name="provider_document")
    op.drop_table("provider_document")
    op.drop_index("ix_demand_event_type_created", table_name="demand_event")
    op.drop_table("demand_event")
    op.drop_table("kiosk_sync_batch")
    op.drop_index(op.f("ix_join_invite_token"), table_name="join_invite")
    op.drop_table("join_invite")
    op.drop_column("provider", "last_rejection_reason")
    op.drop_column("user", "locked_until")
    op.drop_column("user", "failed_login_count")
    op.drop_column("user", "suspended_reason")
    op.drop_column("user", "suspended_at")
    op.drop_column("user", "is_suspended")
    op.drop_column("notification", "read_at")
    op.drop_constraint("ck_notification_channel", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_channel",
        "notification",
        "channel IN ('websocket','email','logger')",
    )
