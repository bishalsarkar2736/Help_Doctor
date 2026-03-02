"""add no_show to appointment_status enum

Revision ID: 63efdb0bd9b1
Revises: 6bedcb6cd07a
Create Date: 2026-02-08 18:20:19.089540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '63efdb0bd9b1'
down_revision: Union[str, Sequence[str], None] = '6bedcb6cd07a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute(
        "ALTER TYPE appointmentstatus ADD VALUE IF NOT EXISTS 'NO_SHOW'"
    )

def downgrade():
    # PostgreSQL CANNOT remove enum values safely
    pass

