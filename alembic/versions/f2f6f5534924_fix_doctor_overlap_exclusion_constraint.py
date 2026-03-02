"""fix doctor overlap exclusion constraint

Revision ID: f2f6f5534924
Revises: e3d66ca9a354
Create Date: 2026-02-18 10:44:28.471690

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2f6f5534924'
down_revision: Union[str, Sequence[str], None] = 'e3d66ca9a354'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # Backfill existing rows
    op.execute("""
        UPDATE appointments
        SET time_range = tstzrange(
            scheduled_at,
            scheduled_at + interval '30 minutes',
            '[)'
        );
    """)

    # Drop old broken constraint if it exists
    op.execute("""
        ALTER TABLE appointments
        DROP CONSTRAINT IF EXISTS no_overlapping_doctor_appointments;
    """)

    # Add correct exclusion constraint
    op.execute("""
        ALTER TABLE appointments
        ADD CONSTRAINT appointments_no_overlap
        EXCLUDE USING gist (
            doctor_id WITH =,
            time_range WITH &&
        )
        WHERE (status IN ('PENDING', 'CONFIRMED'));
    """)


def downgrade():
    op.execute("""
        ALTER TABLE appointments
        DROP CONSTRAINT IF EXISTS appointments_no_overlap;
    """)
