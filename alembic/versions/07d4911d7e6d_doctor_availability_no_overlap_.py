"""doctor availability no overlap constraint

Revision ID: 07d4911d7e6d
Revises: a9d3ae77478c
Create Date: 2026-03-10 10:55:07.406230

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07d4911d7e6d'
down_revision: Union[str, Sequence[str], None] = 'a9d3ae77478c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    # 1️⃣ Enable extension required for exclusion constraint
    op.execute("""
    CREATE EXTENSION IF NOT EXISTS btree_gist;
    """)

    # 2️⃣ Add generated time_range column
    op.execute("""
    ALTER TABLE doctor_availability
    ADD COLUMN time_range TSRANGE
    GENERATED ALWAYS AS (
        tsrange(
            ('2000-01-01'::date + day_of_week) + start_time,
            ('2000-01-01'::date + day_of_week) + end_time,
            '[)'
        )
    ) STORED;
    """)

    # 3️⃣ Add exclusion constraint
    op.execute("""
    ALTER TABLE doctor_availability
    ADD CONSTRAINT doctor_availability_no_overlap
    EXCLUDE USING gist (
        doctor_id WITH =,
        time_range WITH &&
    )
    WHERE (is_available = true);
    """)


def downgrade():

    op.execute("""
    ALTER TABLE doctor_availability
    DROP CONSTRAINT IF EXISTS doctor_availability_no_overlap;
    """)

    op.execute("""
    ALTER TABLE doctor_availability
    DROP COLUMN IF EXISTS time_range;
    """)
