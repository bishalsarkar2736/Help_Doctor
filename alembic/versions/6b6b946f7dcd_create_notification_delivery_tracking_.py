"""create notification delivery tracking fields

Revision ID: 6b6b946f7dcd
Revises: 59faad47e6bc
Create Date: 2026-06-02 01:15:12.545720

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b6b946f7dcd'
down_revision: Union[str, Sequence[str], None] = '59faad47e6bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.add_column(
        "notifications",
        sa.Column(
            "push_delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "notifications",
        sa.Column(
            "email_delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "notifications",
        sa.Column(
            "delivery_failed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "notifications",
        sa.Column(
            "delivery_error",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_notification_push_delivered",
        "notifications",
        ["push_delivered_at"],
    )

    op.create_index(
        "ix_notification_email_delivered",
        "notifications",
        ["email_delivered_at"],
    )

    op.create_index(
        "ix_notification_delivery_failed",
        "notifications",
        ["delivery_failed_at"],
    )


def downgrade():

    op.drop_index(
        "ix_notification_delivery_failed",
        table_name="notifications",
    )

    op.drop_index(
        "ix_notification_email_delivered",
        table_name="notifications",
    )

    op.drop_index(
        "ix_notification_push_delivered",
        table_name="notifications",
    )

    op.drop_column(
        "notifications",
        "delivery_error",
    )

    op.drop_column(
        "notifications",
        "delivery_failed_at",
    )

    op.drop_column(
        "notifications",
        "email_delivered_at",
    )

    op.drop_column(
        "notifications",
        "push_delivered_at",
    )