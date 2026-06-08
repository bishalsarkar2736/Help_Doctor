"""add reminder_sent to appointments

Revision ID: 29736410008c
Revises: 018c6f01489b
Create Date: 2026-04-01 13:14:18.932680

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '29736410008c'
down_revision: Union[str, Sequence[str], None] = '018c6f01489b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # ✅ Step 1 — Add column with safe default
    op.add_column(
        "appointments",
        sa.Column(
            "reminder_sent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # ✅ Step 2 — Create index
    op.create_index(
        "ix_appointments_reminder_sent",
        "appointments",
        ["reminder_sent"],
        unique=False,
    )

    # ✅ Step 3 — Remove default after creation (best practice)
    op.alter_column(
        "appointments",
        "reminder_sent",
        server_default=None,
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Drop index
    op.drop_index(
        "ix_appointments_reminder_sent",
        table_name="appointments",
    )

    # Drop column
    op.drop_column(
        "appointments",
        "reminder_sent",
    )