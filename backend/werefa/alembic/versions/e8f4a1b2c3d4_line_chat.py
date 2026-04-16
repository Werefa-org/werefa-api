"""Line chat messages and service toggle

Revision ID: e8f4a1b2c3d4
Revises: c6f1a8e4d2b9
Create Date: 2026-05-24 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "e8f4a1b2c3d4"
down_revision = "c6f1a8e4d2b9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "service_item",
        sa.Column("line_chat_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_table(
        "line_chat_message",
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_item_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["author_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_item_id"], ["service_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_line_chat_message_service_item_id",
        "line_chat_message",
        ["service_item_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_line_chat_message_service_item_id", table_name="line_chat_message")
    op.drop_table("line_chat_message")
    op.drop_column("service_item", "line_chat_enabled")
