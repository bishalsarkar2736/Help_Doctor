"""add processing_started_at index to outbox_events

Revision ID: cbbaa1037d4a
Revises: 89e06e4bca7f
Create Date: 2026-04-16 20:26:22.473642

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'cbbaa1037d4a'
down_revision: Union[str, Sequence[str], None] = '89e06e4bca7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    # 1️⃣ Add column FIRST
    op.add_column(
        "outbox_events",
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # 2️⃣ Then create index
    op.create_index(
        "ix_outbox_events_processing_started_at",
        "outbox_events",
        ["processing_started_at"],
    )


def downgrade():

    # 1️⃣ Drop index first
    op.drop_index(
        "ix_outbox_events_processing_started_at",
        table_name="outbox_events",
    )

    # 2️⃣ Then drop column
    op.drop_column(
        "outbox_events",
        "processing_started_at",
    )