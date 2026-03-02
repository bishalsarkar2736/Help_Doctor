"""add version column to appointments

Revision ID: f73b6d50a048
Revises: a9df48ec595f
Create Date: 2026-03-02 12:36:57.675945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f73b6d50a048'
down_revision: Union[str, Sequence[str], None] = 'a9df48ec595f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'appointments',
        sa.Column(
            'version',
            sa.Integer(),
            server_default='1',
            nullable=False
        )
    )

def downgrade() -> None:
    op.drop_column('appointments', 'version')