"""add outbox ready index

Revision ID: 709dc0523c33
Revises: e0cd494ec869
Create Date: 2026-03-04 21:48:37.416415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '709dc0523c33'
down_revision: Union[str, Sequence[str], None] = 'e0cd494ec869'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_index(
        "idx_outbox_ready",
        "outbox_events",
        ["is_processed", "failed_at", "next_retry_at", "created_at"],
    )

def downgrade():
    op.drop_index("idx_outbox_ready", table_name="outbox_events")
