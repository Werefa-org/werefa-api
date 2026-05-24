"""Add VIP priority to queue_entry and vip settings to service_item

Revision ID: c6f1a8e4d2b9
Revises: b5e9f3a2c1d7
Create Date: 2026-05-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c6f1a8e4d2b9'
down_revision = 'b5e9f3a2c1d7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('queue_entry', sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))
    op.create_index('ix_queue_entry_priority', 'queue_entry', ['priority'], unique=False)

    op.add_column('service_item', sa.Column('allow_vip', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('service_item', sa.Column('vip_code', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('service_item', 'vip_code')
    op.drop_column('service_item', 'allow_vip')

    op.drop_index('ix_queue_entry_priority', table_name='queue_entry')
    op.drop_column('queue_entry', 'priority')
