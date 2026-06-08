"""remove obsolete appointment_audit_log

Revision ID: 07aeb0972860
Revises: 921ccae4c4f0
Create Date: 2026-03-06 15:41:20.317701

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07aeb0972860'
down_revision: Union[str, Sequence[str], None] = '921ccae4c4f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("DROP TABLE IF EXISTS appointment_audit_log")

def downgrade():
    pass
