"""remove unique constraint from appointment_id in prescriptions

Revision ID: 9af9b596c200
Revises: c9ce1c126b4a
Create Date: 2026-05-28 00:24:32.989658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9af9b596c200'
down_revision: Union[str, Sequence[str], None] = 'c9ce1c126b4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.drop_constraint(
        "prescriptions_appointment_id_key",
        "prescriptions",
        type_="unique",
    )

def downgrade():
    op.create_unique_constraint(
        "prescriptions_appointment_id_key",
        "prescriptions",
        ["appointment_id"],
    )