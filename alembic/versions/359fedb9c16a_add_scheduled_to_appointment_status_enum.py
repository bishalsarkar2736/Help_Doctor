"""add scheduled to appointment status enum

Revision ID: 359fedb9c16a
Revises: ef482b3eb633
Create Date: 2026-02-05 10:29:53.052188

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '359fedb9c16a'
down_revision: Union[str, Sequence[str], None] = 'ef482b3eb633'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute(
        "ALTER TYPE appointmentstatus ADD VALUE IF NOT EXISTS 'SCHEDULED'"
    )



def downgrade() -> None:
    """Downgrade schema."""
    pass
