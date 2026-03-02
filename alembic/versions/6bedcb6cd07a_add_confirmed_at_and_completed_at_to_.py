"""add confirmed_at and completed_at to appointment

Revision ID: 6bedcb6cd07a
Revises: 359fedb9c16a
Create Date: 2026-02-07 23:48:52.510095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bedcb6cd07a'
down_revision: Union[str, Sequence[str], None] = '359fedb9c16a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "appointments",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("appointments", "completed_at")
    op.drop_column("appointments", "confirmed_at")

