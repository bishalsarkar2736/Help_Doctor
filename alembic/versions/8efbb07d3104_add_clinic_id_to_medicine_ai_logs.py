"""add clinic_id to medicine_ai_logs

Revision ID: 8efbb07d3104
Revises: 655f4a885bd5
Create Date: 2026-06-15 00:03:13.164345

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8efbb07d3104'
down_revision: Union[str, Sequence[str], None] = '655f4a885bd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.add_column(
        "medicine_ai_logs",
        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_medicine_ai_logs_clinic_id",
        "medicine_ai_logs",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_medicine_ai_logs_clinic_id",
        "medicine_ai_logs",
        ["clinic_id"],
    )

def downgrade():

    op.drop_index(
        "ix_medicine_ai_logs_clinic_id",
        table_name="medicine_ai_logs",
    )

    op.drop_constraint(
        "fk_medicine_ai_logs_clinic_id",
        "medicine_ai_logs",
        type_="foreignkey",
    )

    op.drop_column(
        "medicine_ai_logs",
        "clinic_id",
    )