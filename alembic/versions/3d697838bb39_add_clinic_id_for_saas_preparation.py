"""add clinic_id for saas preparation

Revision ID: 3d697838bb39
Revises: 2413179f2d3c
Create Date: 2026-06-11 22:43:49.728190

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d697838bb39'
down_revision: Union[str, Sequence[str], None] = '2413179f2d3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    # doctors
    op.add_column(
        "doctors",
        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_doctors_clinic_id",
        "doctors",
        ["clinic_id"],
    )

    op.create_foreign_key(
        "fk_doctors_clinic_id",
        "doctors",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # appointments
    op.add_column(
        "appointments",
        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_appointments_clinic_id",
        "appointments",
        ["clinic_id"],
    )

    op.create_foreign_key(
        "fk_appointments_clinic_id",
        "appointments",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # prescriptions
    op.add_column(
        "prescriptions",
        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_prescriptions_clinic_id",
        "prescriptions",
        ["clinic_id"],
    )

    op.create_foreign_key(
        "fk_prescriptions_clinic_id",
        "prescriptions",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # payments
    op.add_column(
        "payments",
        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_payments_clinic_id",
        "payments",
        ["clinic_id"],
    )

    op.create_foreign_key(
        "fk_payments_clinic_id",
        "payments",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():

    # payments
    op.drop_constraint(
        "fk_payments_clinic_id",
        "payments",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_payments_clinic_id",
        table_name="payments",
    )

    op.drop_column(
        "payments",
        "clinic_id",
    )

    # prescriptions
    op.drop_constraint(
        "fk_prescriptions_clinic_id",
        "prescriptions",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_prescriptions_clinic_id",
        table_name="prescriptions",
    )

    op.drop_column(
        "prescriptions",
        "clinic_id",
    )

    # appointments
    op.drop_constraint(
        "fk_appointments_clinic_id",
        "appointments",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_appointments_clinic_id",
        table_name="appointments",
    )

    op.drop_column(
        "appointments",
        "clinic_id",
    )

    # doctors
    op.drop_constraint(
        "fk_doctors_clinic_id",
        "doctors",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_doctors_clinic_id",
        table_name="doctors",
    )

    op.drop_column(
        "doctors",
        "clinic_id",
    )
