"""add clinic_id to medicine_ai_error_logs

Revision ID: fff0ceffe873
Revises: a3bb7c81ba00
Create Date: 2026-07-10 12:39:16.657803

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fff0ceffe873'
down_revision: Union[str, Sequence[str], None] = 'a3bb7c81ba00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1. Add as nullable first
    op.add_column(
        "medicine_ai_error_logs",
        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    # 2. Create FK
    op.create_foreign_key(
        "fk_medicine_ai_error_logs_clinic",
        "medicine_ai_error_logs",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 3. Create index
    op.create_index(
        op.f("ix_medicine_ai_error_logs_clinic_id"),
        "medicine_ai_error_logs",
        ["clinic_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_medicine_ai_error_logs_clinic_id"),
        table_name="medicine_ai_error_logs",
    )

    op.drop_constraint(
        "fk_medicine_ai_error_logs_clinic",
        "medicine_ai_error_logs",
        type_="foreignkey",
    )

    op.drop_column(
        "medicine_ai_error_logs",
        "clinic_id",
    )