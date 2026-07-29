"""add email verification

Revision ID: c52e2e07e39e
Revises: 07ac4337de9b
Create Date: 2026-07-15 13:31:35.155727

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c52e2e07e39e'
down_revision: Union[str, Sequence[str], None] = '07ac4337de9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    #
    # Add users.is_email_verified
    #
    op.add_column(
        "users",
        sa.Column(
            "is_email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    #
    # Create email_verification_tokens
    #
    op.create_table(
        "email_verification_tokens",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),

        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),

        sa.Column(
            "token_hash",
            sa.String(length=64),
            nullable=False,
        ),

        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),

        sa.Column(
            "used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    #
    # Indexes
    #
    op.create_index(
        op.f("ix_email_verification_tokens_id"),
        "email_verification_tokens",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_email_verification_tokens_user_id"),
        "email_verification_tokens",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_email_verification_tokens_token_hash"),
        "email_verification_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:

    op.drop_index(
        op.f("ix_email_verification_tokens_token_hash"),
        table_name="email_verification_tokens",
    )

    op.drop_index(
        op.f("ix_email_verification_tokens_user_id"),
        table_name="email_verification_tokens",
    )

    op.drop_index(
        op.f("ix_email_verification_tokens_id"),
        table_name="email_verification_tokens",
    )

    op.drop_table("email_verification_tokens")

    op.drop_column(
        "users",
        "is_email_verified",
    )