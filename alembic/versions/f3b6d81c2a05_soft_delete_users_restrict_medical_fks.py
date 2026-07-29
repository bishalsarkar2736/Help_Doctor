"""soft-delete users; RESTRICT medical/financial FKs

Before this migration a single `DELETE FROM users` silently destroyed the
patient's entire appointment, prescription, payment and rating history via
ON DELETE CASCADE. Medical and financial records carry retention obligations
and must outlive the account.

Two changes:

1. `users.deleted_at` — soft delete, mirroring `clinics.deleted_at`.
2. The nine FKs that reach medical/financial rows become RESTRICT, so the
   database itself refuses a hard delete. Ephemeral rows (tokens, sessions,
   notifications, push subscriptions) keep CASCADE — those *should* disappear.

Revision ID: f3b6d81c2a05
Revises: e7a2c94f60b8
Create Date: 2026-07-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3b6d81c2a05"
down_revision: Union[str, Sequence[str], None] = "e7a2c94f60b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (constraint, table, local col, target table, target col)
RETAINED_FKS = [
    ("appointments_patient_id_fkey", "appointments", "patient_id", "users", "id"),
    ("appointments_doctor_id_fkey", "appointments", "doctor_id", "doctors", "id"),
    ("prescriptions_patient_id_fkey", "prescriptions", "patient_id", "users", "id"),
    ("prescriptions_doctor_id_fkey", "prescriptions", "doctor_id", "doctors", "id"),
    ("payments_patient_id_fkey", "payments", "patient_id", "users", "id"),
    ("doctor_ratings_patient_id_fkey", "doctor_ratings", "patient_id", "users", "id"),
    ("doctor_ratings_doctor_id_fkey", "doctor_ratings", "doctor_id", "doctors", "id"),
    ("patients_user_id_fkey", "patients", "user_id", "users", "id"),
    ("doctors_user_id_fkey", "doctors", "user_id", "users", "id"),
    # Same defect one level down: deleting an appointment would have destroyed
    # the prescription issued at it and the payment taken for it.
    (
        "prescriptions_appointment_id_fkey",
        "prescriptions",
        "appointment_id",
        "appointments",
        "id",
    ),
    ("payments_appointment_id_fkey", "payments", "appointment_id", "appointments", "id"),
]


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    for name, table, col, ref_table, ref_col in RETAINED_FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            ref_table,
            [col],
            [ref_col],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    for name, table, col, ref_table, ref_col in RETAINED_FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            ref_table,
            [col],
            [ref_col],
            ondelete="CASCADE",
        )

    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deleted_at")
