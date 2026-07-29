"""add user mfa fields

Revision ID: b4d9e2f710a3
Revises: f3a8b1c05e21
Create Date: 2026-07-26 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4d9e2f710a3"
down_revision: Union[str, Sequence[str], None] = "f3a8b1c05e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mfa_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "users",
        sa.Column("mfa_secret", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "mfa_enabled")
