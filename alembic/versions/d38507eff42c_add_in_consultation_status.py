"""add in consultation status

Revision ID: d38507eff42c
Revises: 9cf6ed5c9a35
Create Date: 2026-05-17 21:22:02.676592

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd38507eff42c'
down_revision: Union[str, Sequence[str], None] = '9cf6ed5c9a35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.execute(
        """
        ALTER TYPE appointmentstatus
        ADD VALUE IF NOT EXISTS 'IN_CONSULTATION'
        """
    )


def downgrade():
    pass