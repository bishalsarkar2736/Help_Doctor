"""add whatsapp delivery tracking to notifications

Revision ID: 8606cb8b3888
Revises: 5a8f0f3c6d1e
Create Date: 2026-07-05 23:48:16.633603

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8606cb8b3888'
down_revision: Union[str, Sequence[str], None] = '5a8f0f3c6d1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.add_column(
        "notifications",
        sa.Column(
            "whatsapp_delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "notifications",
        sa.Column(
            "whatsapp_failed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "notifications",
        sa.Column(
            "whatsapp_error",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_notification_whatsapp_delivered",
        "notifications",
        ["whatsapp_delivered_at"],
    )

    op.create_index(
        "ix_notification_whatsapp_failed",
        "notifications",
        ["whatsapp_failed_at"],
    )


def downgrade() -> None:

    op.drop_index(
        "ix_notification_whatsapp_failed",
        table_name="notifications",
    )

    op.drop_index(
        "ix_notification_whatsapp_delivered",
        table_name="notifications",
    )

    op.drop_column(
        "notifications",
        "whatsapp_error",
    )

    op.drop_column(
        "notifications",
        "whatsapp_failed_at",
    )

    op.drop_column(
        "notifications",
        "whatsapp_delivered_at",
    )