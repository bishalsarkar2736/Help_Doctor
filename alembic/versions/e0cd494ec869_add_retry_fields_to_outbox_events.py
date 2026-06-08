"""add retry fields to outbox events

Revision ID: e0cd494ec869
Revises: cceca186f774
Create Date: 2026-03-04 21:43:16.890508

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0cd494ec869'
down_revision: Union[str, Sequence[str], None] = 'cceca186f774'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # retry_count already exists → DO NOT add again

    op.add_column(
        "outbox_events",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="5"),
    )

    op.add_column(
        "outbox_events",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "outbox_events",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.alter_column("outbox_events", "max_retries", server_default=None)


def downgrade():
    op.drop_column("outbox_events", "failed_at")
    op.drop_column("outbox_events", "next_retry_at")
    op.drop_column("outbox_events", "max_retries")
    # do NOT drop retry_count