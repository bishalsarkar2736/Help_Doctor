"""create notification preferences table

Revision ID: 59faad47e6bc
Revises: de8f23c973a2
Create Date: 2026-06-02 00:35:56.851668

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '59faad47e6bc'
down_revision: Union[str, Sequence[str], None] = 'de8f23c973a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "notification_preferences",

        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "email_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),

        sa.Column(
            "push_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),

        sa.Column(
            "realtime_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),

        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint(
            "user_id",
            name="pk_notification_preferences",
        ),
    )

    # Backfill existing users
    op.execute(
        """
        INSERT INTO notification_preferences (
            user_id,
            email_enabled,
            push_enabled,
            realtime_enabled
        )
        SELECT
            id,
            TRUE,
            TRUE,
            TRUE
        FROM users
        ON CONFLICT DO NOTHING
        """
    )

    # Remove server defaults after backfill
    op.alter_column(
        "notification_preferences",
        "email_enabled",
        server_default=None,
    )

    op.alter_column(
        "notification_preferences",
        "push_enabled",
        server_default=None,
    )

    op.alter_column(
        "notification_preferences",
        "realtime_enabled",
        server_default=None,
    )


def downgrade() -> None:

    op.drop_table(
        "notification_preferences"
    )