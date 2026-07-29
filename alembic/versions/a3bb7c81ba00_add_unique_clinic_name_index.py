"""add unique clinic name index

Revision ID: a3bb7c81ba00
Revises: 49eea1411563
Create Date: 2026-07-10 00:10:36.320706

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3bb7c81ba00'
down_revision: Union[str, Sequence[str], None] = '49eea1411563'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("""
        CREATE UNIQUE INDEX uq_clinic_name_lower
        ON clinics (LOWER(name));
    """)


def downgrade():
    op.execute("""
        DROP INDEX IF EXISTS uq_clinic_name_lower;
    """)
