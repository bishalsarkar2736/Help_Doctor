"""add event_id to notifications

Revision ID: 81b9c3a4b309
Revises: 709dc0523c33
Create Date: 2026-03-04 22:06:29.477038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '81b9c3a4b309'
down_revision: Union[str, Sequence[str], None] = '709dc0523c33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Add column (nullable first to avoid failure if table has rows)
    op.add_column(
        "notifications",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Add foreign key
    op.create_foreign_key(
        "fk_notifications_event_id",
        "notifications",
        "outbox_events",
        ["event_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add unique constraint
    op.create_unique_constraint(
        "uq_notifications_event_id",
        "notifications",
        ["event_id"],
    )

    # If table is empty, make it NOT NULL
    op.alter_column("notifications", "event_id", nullable=False)


def downgrade():
    op.drop_constraint(
        "uq_notifications_event_id",
        "notifications",
        type_="unique",
    )

    op.drop_constraint(
        "fk_notifications_event_id",
        "notifications",
        type_="foreignkey",
    )

    op.drop_column("notifications", "event_id")
