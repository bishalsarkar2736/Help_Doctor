"""add google authentication support

Revision ID: 9b5e12cbaae0
Revises: 5f6c1c2d3e4f
Create Date: 2026-07-15 00:22:10.148964

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b5e12cbaae0'
down_revision: Union[str, Sequence[str], None] = '5f6c1c2d3e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make password nullable
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(length=255),
        nullable=True,
    )

    # Make google_id unique
    op.create_unique_constraint(
        "uq_users_google_id",
        "users",
        ["google_id"],
    )


def downgrade() -> None:
    # Remove unique constraint
    op.drop_constraint(
        "uq_users_google_id",
        "users",
        type_="unique",
    )

    # Restore NOT NULL
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(length=255),
        nullable=False,
    )