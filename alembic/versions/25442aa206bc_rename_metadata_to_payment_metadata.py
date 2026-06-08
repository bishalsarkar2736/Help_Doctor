"""rename metadata to payment_metadata

Revision ID: 25442aa206bc
Revises: 80681b1112b2
Create Date: 2026-03-12 22:02:06.422430

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '25442aa206bc'
down_revision: Union[str, Sequence[str], None] = '80681b1112b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column(
        "payments",
        "metadata",
        new_column_name="payment_metadata"
    )


def downgrade():
    op.alter_column(
        "payments",
        "payment_metadata",
        new_column_name="metadata"
    )