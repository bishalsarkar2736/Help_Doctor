"""add idempotency keys

Revision ID: a363cf848ee0
Revises: 01de1781f7a9
Create Date: 2026-03-06 23:02:56.626414

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a363cf848ee0'
down_revision: Union[str, Sequence[str], None] = '01de1781f7a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_idempotency_user_key",
        "idempotency_keys",
        ["user_id", "key"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_idempotency_user_key", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
