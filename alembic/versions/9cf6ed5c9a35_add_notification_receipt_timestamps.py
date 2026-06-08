"""add notification receipt timestamps

Revision ID: 9cf6ed5c9a35
Revises: 2896f9fd1e9d
Create Date: 2026-05-14 23:42:18.324916

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9cf6ed5c9a35'
down_revision: Union[str, Sequence[str], None] = '2896f9fd1e9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "notifications",
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("notifications", "seen_at")
    op.drop_column("notifications", "delivered_at")