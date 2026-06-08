"""add dead_letter_events table

Revision ID: 3a267de4882e
Revises: cbbaa1037d4a
Create Date: 2026-04-17 01:33:02.384136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3a267de4882e'
down_revision: Union[str, Sequence[str], None] = 'cbbaa1037d4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # ✅ ensure UUID generator
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.create_table(
        "dead_letter_events",

        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),

        sa.Column(
            "original_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            "event_type",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "payload",
            postgresql.JSONB(),  # ✅ better
            nullable=False,
        ),

        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "error_message",
            sa.String(length=500),
            nullable=False,
        ),

        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_dead_letter_events_original_event_id",
        "dead_letter_events",
        ["original_event_id"],
    )

    op.create_index(
        "ix_dead_letter_events_event_type",
        "dead_letter_events",
        ["event_type"],
    )

    op.create_index(
        "ix_dead_letter_events_failed_at",
        "dead_letter_events",
        ["failed_at"],
    )


def downgrade():
    op.drop_index("ix_dead_letter_events_failed_at", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_event_type", table_name="dead_letter_events")
    op.drop_index("ix_dead_letter_events_original_event_id", table_name="dead_letter_events")

    op.drop_table("dead_letter_events")