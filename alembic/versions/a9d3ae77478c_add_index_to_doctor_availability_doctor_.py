"""add index to doctor_availability doctor_id

Revision ID: a9d3ae77478c
Revises: a363cf848ee0
Create Date: 2026-03-09 11:42:03.788150

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a9d3ae77478c'
down_revision: Union[str, Sequence[str], None] = 'a363cf848ee0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_index(
        "idx_doctor_availability_doctor_id",
        "doctor_availability",
        ["doctor_id"],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "idx_doctor_availability_doctor_id",
        table_name="doctor_availability",
    )

