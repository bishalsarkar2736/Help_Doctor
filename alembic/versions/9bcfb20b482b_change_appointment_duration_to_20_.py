"""change appointment duration to 20 minutes

Revision ID: 9bcfb20b482b
Revises: 0106b2db435c
Create Date: 2026-07-11 11:55:10.030581

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9bcfb20b482b'
down_revision: Union[str, Sequence[str], None] = '0106b2db435c'
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
                NEW.scheduled_at + interval '20 minutes',
                '[)'
            );
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    UPDATE appointments
    SET time_range =
        tstzrange(
            scheduled_at,
            scheduled_at + interval '20 minutes',
            '[)'
        );
    """)


def downgrade():
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
    UPDATE appointments
    SET time_range =
        tstzrange(
            scheduled_at,
            scheduled_at + interval '30 minutes',
            '[)'
        );
    """)