"""enable btree_gist extension

Revision ID: c2837425acaa
Revises: b48900c1a72f
Create Date: 2026-02-17 22:22:06.352344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2837425acaa'
down_revision: Union[str, Sequence[str], None] = 'b48900c1a72f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def downgrade():
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
