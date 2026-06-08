"""upgrade outbox_events lifecycle model

Revision ID: bc79485100f3
Revises: 3a267de4882e
Create Date: 2026-05-05 18:13:40.381417

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc79485100f3'
down_revision: Union[str, Sequence[str], None] = '3a267de4882e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Add new lifecycle columns
    op.add_column(
        "outbox_events",
        sa.Column("status", sa.String(length=20), nullable=True),
    )

    op.add_column(
        "outbox_events",
        sa.Column("last_error", sa.String(length=500), nullable=True),
    )

    # 2) Backfill status from old boolean lifecycle
    op.execute("""
        UPDATE outbox_events
        SET status = CASE
            WHEN is_processed = true THEN 'processed'
            ELSE 'pending'
        END
    """)

    # 3) Make status required + safe default during rollout
    op.alter_column(
        "outbox_events",
        "status",
        existing_type=sa.String(length=20),
        nullable=False,
        server_default="pending",
    )

    # 4) Drop obsolete old worker indexes first
    op.drop_index("idx_outbox_ready", table_name="outbox_events")
    op.drop_index("ix_outbox_events_is_processed", table_name="outbox_events")

    # 5) Drop obsolete old lifecycle column
    op.drop_column("outbox_events", "is_processed")

    # 6) Create new lifecycle indexes
    op.create_index(
        "ix_outbox_events_status",
        "outbox_events",
        ["status"],
        unique=False,
    )

    op.create_index(
        "ix_outbox_events_next_retry_at",
        "outbox_events",
        ["next_retry_at"],
        unique=False,
    )

    # 7) Replacement worker-ready composite index
    op.create_index(
        "idx_outbox_ready_v2",
        "outbox_events",
        ["status", "failed_at", "next_retry_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # 1) Restore old lifecycle boolean
    op.add_column(
        "outbox_events",
        sa.Column(
            "is_processed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # 2) Backfill boolean from new lifecycle state
    op.execute("""
        UPDATE outbox_events
        SET is_processed = CASE
            WHEN status = 'processed' THEN true
            ELSE false
        END
    """)

    # 3) Restore old indexes
    op.create_index(
        "ix_outbox_events_is_processed",
        "outbox_events",
        ["is_processed"],
        unique=False,
    )

    op.create_index(
        "idx_outbox_ready",
        "outbox_events",
        ["is_processed", "failed_at", "next_retry_at", "created_at"],
        unique=False,
    )

    # 4) Drop new indexes
    op.drop_index("idx_outbox_ready_v2", table_name="outbox_events")
    op.drop_index("ix_outbox_events_next_retry_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status", table_name="outbox_events")

    # 5) Drop new columns
    op.drop_column("outbox_events", "last_error")
    op.drop_column("outbox_events", "status")