"""Add extended profile fields to provider and service_item

Revision ID: a4d8f2c1b9e0
Revises: fe56fa70289e
Create Date: 2026-05-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a4d8f2c1b9e0'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('provider', sa.Column('category', sa.String(length=64), nullable=True))
    op.add_column('provider', sa.Column('description', sa.String(length=1000), nullable=True))
    op.add_column('provider', sa.Column('city', sa.String(length=100), nullable=True))
    op.add_column('provider', sa.Column('address', sa.String(length=500), nullable=True))
    op.add_column('provider', sa.Column('phone', sa.String(length=20), nullable=True))
    op.add_column('provider', sa.Column('show_phone_public', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('provider', sa.Column('website', sa.String(length=200), nullable=True))
    op.add_column('provider', sa.Column('biz_email', sa.String(length=255), nullable=True))

    op.add_column('service_item', sa.Column('description', sa.String(length=1000), nullable=True))
    op.add_column('service_item', sa.Column('requirements', sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column('service_item', 'requirements')
    op.drop_column('service_item', 'description')

    op.drop_column('provider', 'biz_email')
    op.drop_column('provider', 'website')
    op.drop_column('provider', 'show_phone_public')
    op.drop_column('provider', 'phone')
    op.drop_column('provider', 'address')
    op.drop_column('provider', 'city')
    op.drop_column('provider', 'description')
    op.drop_column('provider', 'category')
