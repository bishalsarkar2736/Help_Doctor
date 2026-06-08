"""add outbox retry index

Revision ID: 2896f9fd1e9d
Revises: bc79485100f3
Create Date: 2026-05-13 15:25:54.294409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2896f9fd1e9d'
down_revision: Union[str, Sequence[str], None] = 'bc79485100f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ------------------------------------------------------------------
    # correlation_id
    # ------------------------------------------------------------------

    op.add_column(
        "outbox_events",
        sa.Column(
            "correlation_id",
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_outbox_events_correlation_id",
        "outbox_events",
        ["correlation_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # composite retry index
    # ------------------------------------------------------------------

    op.create_index(
        "ix_outbox_pending_retry",
        "outbox_events",
        ["status", "next_retry_at"],
        unique=False,
    )


def downgrade() -> None:

    # ------------------------------------------------------------------
    # remove composite retry index
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_outbox_pending_retry",
        table_name="outbox_events",
    )

    # ------------------------------------------------------------------
    # remove correlation_id
    # ------------------------------------------------------------------

    op.drop_index(
        "ix_outbox_events_correlation_id",
        table_name="outbox_events",
    )

    op.drop_column(
        "outbox_events",
        "correlation_id",
    )