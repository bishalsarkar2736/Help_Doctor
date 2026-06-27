"""add consultation fee fields

Revision ID: eba4f4e128ce
Revises: df60e96699e9
Create Date: 2026-06-24 20:53:31.676793

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eba4f4e128ce'
down_revision: Union[str, Sequence[str], None] = 'df60e96699e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "doctors",
        sa.Column(
            "consultation_fee",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
    )

    op.add_column(
        "appointments",
        sa.Column(
            "consultation_fee",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
    )


def downgrade() -> None:
    op.drop_column("appointments", "consultation_fee")
    op.drop_column("doctors", "consultation_fee")