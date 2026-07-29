"""add locked status to prescription enum

Revision ID: 5a8f0f3c6d1e
Revises: c9ce1c126b4a
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5a8f0f3c6d1e'
down_revision: Union[str, Sequence[str], None] = '5dcf7de83d71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE prescriptionstatus "
        "ADD VALUE IF NOT EXISTS 'LOCKED'"
    )


def downgrade() -> None:
    # PostgreSQL does not support dropping enum values directly.
    # This downgrade is intentionally left as a no-op for safety.
    pass
