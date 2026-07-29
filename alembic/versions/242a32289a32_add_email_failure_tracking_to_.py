"""add email failure tracking to notifications

Revision ID: 242a32289a32
Revises: b07c4b28f6d4
Create Date: 2026-07-06 02:59:50.134812

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '242a32289a32'
down_revision: Union[str, Sequence[str], None] = 'b07c4b28f6d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.add_column(
        "notifications",
        sa.Column(
            "email_failed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "notifications",
        sa.Column(
            "email_error",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_notification_email_failed",
        "notifications",
        ["email_failed_at"],
    )


def downgrade() -> None:

    op.drop_index(
        "ix_notification_email_failed",
        table_name="notifications",
    )

    op.drop_column(
        "notifications",
        "email_error",
    )

    op.drop_column(
        "notifications",
        "email_failed_at",
    )
