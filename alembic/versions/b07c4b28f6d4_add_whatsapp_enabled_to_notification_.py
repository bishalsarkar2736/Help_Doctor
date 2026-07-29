"""add whatsapp_enabled to notification_preferences

Revision ID: b07c4b28f6d4
Revises: 8606cb8b3888
Create Date: 2026-07-05 23:54:49.619495

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b07c4b28f6d4'
down_revision: Union[str, Sequence[str], None] = '8606cb8b3888'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification_preferences",
        sa.Column(
            "whatsapp_enabled",
            sa.Boolean(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "notification_preferences",
        "whatsapp_enabled",
    )