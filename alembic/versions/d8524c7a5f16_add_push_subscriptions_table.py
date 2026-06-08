"""add push_subscriptions table

Revision ID: d8524c7a5f16
Revises: 29736410008c
Create Date: 2026-04-09 10:38:42.748962

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8524c7a5f16'
down_revision: Union[str, Sequence[str], None] = '29736410008c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        'push_subscriptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('endpoint', sa.Text(), nullable=False, unique=True),
        sa.Column('keys', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('push_subscriptions')
