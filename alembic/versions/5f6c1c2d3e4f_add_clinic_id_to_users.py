"""add clinic_id to users

Revision ID: 5f6c1c2d3e4f
Revises: cf88ffce4077
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5f6c1c2d3e4f'
down_revision: Union[str, Sequence[str], None] = '9bcfb20b482b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('clinic_id', sa.Integer(), nullable=True),
    )
    op.create_index(op.f('ix_users_clinic_id'), 'users', ['clinic_id'], unique=False)
    op.create_foreign_key(
        'fk_users_clinic_id',
        'users',
        'clinics',
        ['clinic_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_users_clinic_id', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_clinic_id'), table_name='users')
    op.drop_column('users', 'clinic_id')
