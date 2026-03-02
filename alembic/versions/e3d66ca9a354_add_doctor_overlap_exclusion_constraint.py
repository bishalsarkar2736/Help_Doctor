"""add doctor overlap exclusion constraint

Revision ID: e3d66ca9a354
Revises: 33b306f9fa16
Create Date: 2026-02-17 23:24:59.899281

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3d66ca9a354'
down_revision: Union[str, Sequence[str], None] = '33b306f9fa16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    op.execute("""
        ALTER TABLE appointments
        ADD CONSTRAINT no_overlapping_doctor_appointments
        EXCLUDE USING gist (
            doctor_id WITH =,
            time_range WITH &&
        )
        WHERE (status IN ('PENDING', 'CONFIRMED'));
    """)


def downgrade():
    op.execute("""
        ALTER TABLE appointments
        DROP CONSTRAINT IF EXISTS no_overlapping_doctor_appointments;
    """)