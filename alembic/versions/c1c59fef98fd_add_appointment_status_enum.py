"""add appointment_status enum

Revision ID: c1c59fef98fd
Revises: b07b945ff187
Create Date: 2026-02-15 22:57:41.362265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1c59fef98fd'
down_revision: Union[str, Sequence[str], None] = 'b07b945ff187'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("""
        CREATE TYPE appointment_status AS ENUM (
            'pending',
            'confirmed',
            'completed',
            'cancelled'
        )
    """)

def downgrade():
    op.execute("DROP TYPE appointment_status")

