"""add appointment integrity constraints

Revision ID: f593ef7da81c
Revises: c1c59fef98fd
Create Date: 2026-02-16 10:55:45.387973

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f593ef7da81c'
down_revision: Union[str, Sequence[str], None] = 'c1c59fef98fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_check_constraint(
        "chk_confirmed_requires_timestamp",
        "appointments",
        "(status != 'CONFIRMED') OR (confirmed_at IS NOT NULL)"
    )

    op.create_check_constraint(
        "chk_completed_requires_timestamp",
        "appointments",
        "(status != 'COMPLETED') OR (completed_at IS NOT NULL)",
    )

    op.create_check_constraint(
        "chk_cancelled_requires_timestamp",
        "appointments",
        "(status != 'CANCELLED') OR (cancelled_at IS NOT NULL)",
    )



def downgrade() -> None:
    """Downgrade schema."""
    pass
