"""convert scheduled_at to timestamptz

Revision ID: c7c16c6e4e6d
Revises: 735314315a4b
Create Date: 2026-02-10 11:09:19.688272
"""

from alembic import op
import sqlalchemy as sa

revision = "c7c16c6e4e6d"
down_revision = "63efdb0bd9b1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE appointments
        ALTER COLUMN scheduled_at
        TYPE TIMESTAMP WITH TIME ZONE
        USING scheduled_at AT TIME ZONE 'UTC'
    """)


def downgrade():
    op.execute("""
        ALTER TABLE appointments
        ALTER COLUMN scheduled_at
        TYPE TIMESTAMP WITHOUT TIME ZONE
        USING scheduled_at AT TIME ZONE 'UTC'
    """)
