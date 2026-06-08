"""update push_subscriptions fields

Revision ID: 40a2041bc592
Revises: d8524c7a5f16
Create Date: 2026-04-09 14:31:50.250009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40a2041bc592'
down_revision: Union[str, Sequence[str], None] = 'd8524c7a5f16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1️⃣ Index for user_id
    op.create_index(
        "ix_push_subscriptions_user_id",
        "push_subscriptions",
        ["user_id"],
        unique=False
    )

    # 2️⃣ Ensure user_id NOT NULL
    op.alter_column(
        "push_subscriptions",
        "user_id",
        existing_type=sa.Integer(),
        nullable=False
    )

    # 3️⃣ Convert created_at → TIMESTAMP WITH TIME ZONE (SAFE)
    op.alter_column(
        "push_subscriptions",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        nullable=False,
        existing_server_default=sa.text("now()"),
        postgresql_using="created_at AT TIME ZONE 'UTC'"
    )


def downgrade():
    op.alter_column(
        "push_subscriptions",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        nullable=True,
        existing_server_default=sa.text("now()"),
        postgresql_using="created_at AT TIME ZONE 'UTC'"
    )

    op.alter_column(
        "push_subscriptions",
        "user_id",
        existing_type=sa.Integer(),
        nullable=True
    )

    op.drop_index(
        "ix_push_subscriptions_user_id",
        table_name="push_subscriptions"
    )