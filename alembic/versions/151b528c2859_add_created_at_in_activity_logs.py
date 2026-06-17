"""add created at in activity logs

Revision ID: 151b528c2859
Revises: c93c19a0b266
Create Date: 2026-06-16 11:22:46.423489

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '151b528c2859'
down_revision: Union[str, Sequence[str], None] = 'c93c19a0b266'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.add_column(
        "activity_logs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_activity_logs_created_at",
        "activity_logs",
        ["created_at"],
    )


def downgrade():

    op.drop_index(
        "ix_activity_logs_created_at",
        table_name="activity_logs",
    )

    op.drop_column(
        "activity_logs",
        "created_at",
    )