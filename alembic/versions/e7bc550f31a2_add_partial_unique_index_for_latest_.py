"""add partial unique index for latest prescription

Revision ID: e7bc550f31a2
Revises: 9af9b596c200
Create Date: 2026-05-28 13:23:22.081487

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7bc550f31a2'
down_revision: Union[str, Sequence[str], None] = '9af9b596c200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.execute(
        """
        CREATE UNIQUE INDEX
        one_latest_prescription_per_appointment
        ON prescriptions (appointment_id)
        WHERE is_latest_revision = true
        """
    )


def downgrade():

    op.execute(
        """
        DROP INDEX one_latest_prescription_per_appointment
        """
    )