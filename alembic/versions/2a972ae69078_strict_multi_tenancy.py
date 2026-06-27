"""strict multi tenancy

Revision ID: 2a972ae69078
Revises: 64cdc5803e8e
Create Date: 2026-06-19 23:57:45.612778

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2a972ae69078'
down_revision: Union[str, Sequence[str], None] = '64cdc5803e8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    # =====================================================
    # DOCTORS
    # =====================================================

    op.drop_constraint(
        "fk_doctors_clinic_id",
        "doctors",
        type_="foreignkey",
    )

    op.alter_column(
        "doctors",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_foreign_key(
        "fk_doctors_clinic_id",
        "doctors",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # =====================================================
    # APPOINTMENTS
    # =====================================================

    op.drop_constraint(
        "fk_appointments_clinic_id",
        "appointments",
        type_="foreignkey",
    )

    op.alter_column(
        "appointments",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_foreign_key(
        "fk_appointments_clinic_id",
        "appointments",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # =====================================================
    # PRESCRIPTIONS
    # =====================================================

    op.drop_constraint(
        "fk_prescriptions_clinic_id",
        "prescriptions",
        type_="foreignkey",
    )

    op.alter_column(
        "prescriptions",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_foreign_key(
        "fk_prescriptions_clinic_id",
        "prescriptions",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # =====================================================
    # PAYMENTS
    # =====================================================

    op.drop_constraint(
        "fk_payments_clinic_id",
        "payments",
        type_="foreignkey",
    )

    op.alter_column(
        "payments",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_foreign_key(
        "fk_payments_clinic_id",
        "payments",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # =====================================================
    # ACTIVITY LOGS (only if clinic_id exists)
    # =====================================================

    op.drop_constraint(
        "fk_activity_logs_clinic_id",
        "activity_logs",
        type_="foreignkey",
    )

    op.alter_column(
        "activity_logs",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_foreign_key(
        "fk_activity_logs_clinic_id",
        "activity_logs",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade():

    # =====================================================
    # ACTIVITY LOGS
    # =====================================================

    op.drop_constraint(
        "fk_activity_logs_clinic_id",
        "activity_logs",
        type_="foreignkey",
    )

    op.alter_column(
        "activity_logs",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_foreign_key(
        "fk_activity_logs_clinic_id",
        "activity_logs",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # =====================================================
    # PAYMENTS
    # =====================================================

    op.drop_constraint(
        "fk_payments_clinic_id",
        "payments",
        type_="foreignkey",
    )

    op.alter_column(
        "payments",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_foreign_key(
        "fk_payments_clinic_id",
        "payments",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # =====================================================
    # PRESCRIPTIONS
    # =====================================================

    op.drop_constraint(
        "fk_prescriptions_clinic_id",
        "prescriptions",
        type_="foreignkey",
    )

    op.alter_column(
        "prescriptions",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_foreign_key(
        "fk_prescriptions_clinic_id",
        "prescriptions",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # =====================================================
    # APPOINTMENTS
    # =====================================================

    op.drop_constraint(
        "fk_appointments_clinic_id",
        "appointments",
        type_="foreignkey",
    )

    op.alter_column(
        "appointments",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_foreign_key(
        "fk_appointments_clinic_id",
        "appointments",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # =====================================================
    # DOCTORS
    # =====================================================

    op.drop_constraint(
        "fk_doctors_clinic_id",
        "doctors",
        type_="foreignkey",
    )

    op.alter_column(
        "doctors",
        "clinic_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_foreign_key(
        "fk_doctors_clinic_id",
        "doctors",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )