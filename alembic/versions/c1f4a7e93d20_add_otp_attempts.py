"""add attempts counter to email verification tokens (OTP brute-force guard)

Revision ID: c1f4a7e93d20
Revises: b4d9e2f710a3
Create Date: 2026-07-28 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1f4a7e93d20"
down_revision: Union[str, Sequence[str], None] = "b4d9e2f710a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_verification_tokens",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("email_verification_tokens", "attempts")
