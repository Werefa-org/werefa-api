"""Add category, is_paused, is_private to service_item

Revision ID: b5e9f3a2c1d7
Revises: a4d8f2c1b9e0
Create Date: 2026-05-24 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b5e9f3a2c1d7'
down_revision = 'a4d8f2c1b9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('service_item', sa.Column('category', sa.String(length=64), nullable=True))
    op.add_column('service_item', sa.Column('is_paused', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('service_item', sa.Column('is_private', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('service_item', 'is_private')
    op.drop_column('service_item', 'is_paused')
    op.drop_column('service_item', 'category')
