"""prevent duplicate pending payments

Revision ID: eaabd6b7e65b
Revises: 25442aa206bc
Create Date: 2026-03-12 22:28:07.559109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'eaabd6b7e65b'
down_revision: Union[str, Sequence[str], None] = '25442aa206bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.create_index(
        "idx_unique_pending_payment",
        "payments",
        ["appointment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade():

    op.drop_index(
        "idx_unique_pending_payment",
        table_name="payments",
    )