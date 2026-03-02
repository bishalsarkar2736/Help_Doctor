"""add appointment time_range column

Revision ID: d576fcff7a77
Revises: 4823d1cc0ff5
Create Date: 2026-02-17 22:41:42.842662

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd576fcff7a77'
down_revision: Union[str, Sequence[str], None] = '4823d1cc0ff5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("""
        ALTER TABLE appointments
        ADD COLUMN time_range tstzrange;
    """)


def downgrade():
    op.execute("""
        ALTER TABLE appointments
        DROP COLUMN IF EXISTS time_range;
    """)