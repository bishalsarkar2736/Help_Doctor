"""remove version server default

Revision ID: 075ec6110115
Revises: f73b6d50a048
Create Date: 2026-03-02 12:53:19.968032

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '075ec6110115'
down_revision: Union[str, Sequence[str], None] = 'f73b6d50a048'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column(
        "appointments",
        "version",
        server_default=None
    )


def downgrade():
    op.alter_column(
        "appointments",
        "version",
        server_default="1"
    )
