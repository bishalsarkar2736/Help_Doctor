"""add notification idempotency constraint

Revision ID: 89e06e4bca7f
Revises: 40a2041bc592
Create Date: 2026-04-16 20:18:09.482783

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '89e06e4bca7f'
down_revision: Union[str, Sequence[str], None] = '40a2041bc592'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    # 1️⃣ Drop old incorrect unique constraint (event_id only)
    op.drop_constraint(
        "uq_notifications_event_id",
        "notifications",
        type_="unique",
    )

    # 2️⃣ Remove invalid rows (event_id NULL)
    op.execute("""
        DELETE FROM notifications
        WHERE event_id IS NULL;
    """)

    # 3️⃣ Enforce NOT NULL on event_id
    op.alter_column(
        "notifications",
        "event_id",
        nullable=False,
    )

    # 4️⃣ Add correct composite unique constraint
    op.create_unique_constraint(
        "uq_notification_event_user",
        "notifications",
        ["event_id", "user_id"],
    )


def downgrade():

    # 1️⃣ Drop composite constraint
    op.drop_constraint(
        "uq_notification_event_user",
        "notifications",
        type_="unique",
    )

    # 2️⃣ Restore old unique constraint (event_id only)
    op.create_unique_constraint(
        "uq_notifications_event_id",
        "notifications",
        ["event_id"],
    )

    # 3️⃣ Allow NULL again
    op.alter_column(
        "notifications",
        "event_id",
        nullable=True,
    )