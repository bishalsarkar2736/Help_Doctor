"""change clinic foreign keys to restrict

Revision ID: cf88ffce4077
Revises: fff0ceffe873
Create Date: 2026-07-10 12:48:04.701131

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf88ffce4077'
down_revision: Union[str, Sequence[str], None] = 'fff0ceffe873'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    tables = [
        ("doctors", "fk_doctors_clinic_id"),
        ("appointments", "fk_appointments_clinic_id"),
        ("prescriptions", "fk_prescriptions_clinic_id"),
        ("payments", "fk_payments_clinic_id"),
        ("medicine_ai_logs", "fk_medicine_ai_logs_clinic_id"),
    ]

    for table, constraint in tables:
        op.drop_constraint(
            constraint,
            table,
            type_="foreignkey",
        )

        op.create_foreign_key(
            constraint,
            table,
            "clinics",
            ["clinic_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade():

    tables = [
        ("doctors", "fk_doctors_clinic_id"),
        ("appointments", "fk_appointments_clinic_id"),
        ("prescriptions", "fk_prescriptions_clinic_id"),
        ("payments", "fk_payments_clinic_id"),
        ("medicine_ai_logs", "fk_medicine_ai_logs_clinic_id"),
    ]

    for table, constraint in tables:
        op.drop_constraint(
            constraint,
            table,
            type_="foreignkey",
        )

        op.create_foreign_key(
            constraint,
            table,
            "clinics",
            ["clinic_id"],
            ["id"],
            ondelete="SET NULL",
        )