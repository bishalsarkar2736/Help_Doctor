"""add waiting queue appointment fields

Revision ID: 49eea1411563
Revises: 242a32289a32
Create Date: 2026-07-07 13:57:04.867115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49eea1411563'
down_revision: Union[str, Sequence[str], None] = '242a32289a32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    # --------------------------------------------------
    # 1. Add new enum values
    # --------------------------------------------------

    op.execute(
        "ALTER TYPE appointmentstatus "
        "ADD VALUE IF NOT EXISTS 'CHECKED_IN';"
    )

    op.execute(
        "ALTER TYPE appointmentstatus "
        "ADD VALUE IF NOT EXISTS 'WAITING';"
    )

    # --------------------------------------------------
    # 2. Add workflow timestamps
    # --------------------------------------------------

    op.add_column(
        "appointments",
        sa.Column(
            "checked_in_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "appointments",
        sa.Column(
            "waiting_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "appointments",
        sa.Column(
            "consultation_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # --------------------------------------------------
    # 3. Queue number
    # --------------------------------------------------

    op.add_column(
        "appointments",
        sa.Column(
            "queue_number",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_appointments_queue_number",
        "appointments",
        ["queue_number"],
    )
    

def downgrade():

    op.drop_index(
        "ix_appointments_queue_number",
        table_name="appointments",
    )

    op.drop_column(
        "appointments",
        "queue_number",
    )

    op.drop_column(
        "appointments",
        "consultation_started_at",
    )

    op.drop_column(
        "appointments",
        "waiting_started_at",
    )

    op.drop_column(
        "appointments",
        "checked_in_at",
    )