"""add appointment time_range trigger

Revision ID: 33b306f9fa16
Revises: d576fcff7a77
Create Date: 2026-02-17 23:22:59.952954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33b306f9fa16'
down_revision: Union[str, Sequence[str], None] = 'd576fcff7a77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION set_appointment_time_range()
        RETURNS trigger AS $$
        BEGIN
            NEW.time_range :=
                tstzrange(
                    NEW.scheduled_at,
                    NEW.scheduled_at + interval '30 minutes',
                    '[)'
                );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER appointment_time_range_trigger
        BEFORE INSERT OR UPDATE OF scheduled_at
        ON appointments
        FOR EACH ROW
        EXECUTE FUNCTION set_appointment_time_range();
    """)


def downgrade():
    op.execute("""
        DROP TRIGGER IF EXISTS appointment_time_range_trigger
        ON appointments;
    """)

    op.execute("""
        DROP FUNCTION IF EXISTS set_appointment_time_range;
    """)