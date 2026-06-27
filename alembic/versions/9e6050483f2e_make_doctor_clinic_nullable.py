"""make doctor clinic nullable

Revision ID: 9e6050483f2e
Revises: 2a972ae69078
Create Date: 2026-06-20 16:01:07.208362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9e6050483f2e'
down_revision: Union[str, Sequence[str], None] = '2a972ae69078'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.alter_column(
        "doctors",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade():

    op.alter_column(
        "doctors",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=False,
    )