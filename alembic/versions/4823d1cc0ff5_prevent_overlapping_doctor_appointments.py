"""prevent overlapping doctor appointments

Revision ID: 4823d1cc0ff5
Revises: c2837425acaa
Create Date: 2026-02-17 22:23:22.282756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4823d1cc0ff5'
down_revision: Union[str, Sequence[str], None] = 'c2837425acaa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    pass


def downgrade():
    pass


