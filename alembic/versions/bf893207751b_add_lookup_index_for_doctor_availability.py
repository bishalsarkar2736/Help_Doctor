"""add lookup index for doctor availability

Revision ID: bf893207751b
Revises: 07d4911d7e6d
Create Date: 2026-03-10 11:22:34.669298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf893207751b'
down_revision: Union[str, Sequence[str], None] = '07d4911d7e6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_index(
        "idx_doctor_availability_lookup",
        "doctor_availability",
        [
            "doctor_id",
            "day_of_week",
            "is_available",
            "start_time",
            "end_time",
        ],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "idx_doctor_availability_lookup",
        table_name="doctor_availability",
    )
