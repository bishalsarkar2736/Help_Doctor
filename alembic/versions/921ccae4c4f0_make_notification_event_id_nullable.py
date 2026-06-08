"""make notification event_id nullable

Revision ID: 921ccae4c4f0
Revises: 81b9c3a4b309
Create Date: 2026-03-05 14:17:24.619051

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '921ccae4c4f0'
down_revision: Union[str, Sequence[str], None] = '81b9c3a4b309'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "notifications",
        "event_id",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "notifications",
        "event_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
