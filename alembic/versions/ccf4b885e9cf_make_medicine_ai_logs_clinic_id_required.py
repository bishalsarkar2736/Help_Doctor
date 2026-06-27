"""make medicine_ai_logs clinic_id required

Revision ID: ccf4b885e9cf
Revises: 9e6050483f2e
Create Date: 2026-06-22 20:11:41.903893

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ccf4b885e9cf'
down_revision: Union[str, Sequence[str], None] = '9e6050483f2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.drop_constraint(
        "fk_medicine_ai_logs_clinic_id",
        "medicine_ai_logs",
        type_="foreignkey",
    )

    op.alter_column(
        "medicine_ai_logs",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_foreign_key(
        "fk_medicine_ai_logs_clinic_id",
        "medicine_ai_logs",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade():

    op.drop_constraint(
        "fk_medicine_ai_logs_clinic_id",
        "medicine_ai_logs",
        type_="foreignkey",
    )

    op.alter_column(
        "medicine_ai_logs",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_foreign_key(
        "fk_medicine_ai_logs_clinic_id",
        "medicine_ai_logs",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )