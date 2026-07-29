"""add doctor_ratings

Revision ID: e7a2c94f60b8
Revises: d5e8b3c71f42
Create Date: 2026-07-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7a2c94f60b8"
down_revision: Union[str, Sequence[str], None] = "d5e8b3c71f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "doctor_ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("clinic_id", sa.Integer(), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # One rating per visit — the anti-brigading guarantee.
        sa.UniqueConstraint(
            "appointment_id", name="uq_doctor_ratings_appointment_id"
        ),
        sa.CheckConstraint(
            "stars >= 1 AND stars <= 5", name="ck_doctor_ratings_stars_range"
        ),
    )

    op.create_index(
        "ix_doctor_ratings_appointment_id",
        "doctor_ratings",
        ["appointment_id"],
    )
    op.create_index(
        "ix_doctor_ratings_patient_id", "doctor_ratings", ["patient_id"]
    )
    op.create_index(
        "ix_doctor_ratings_doctor_id", "doctor_ratings", ["doctor_id"]
    )
    op.create_index(
        "ix_doctor_ratings_clinic_id", "doctor_ratings", ["clinic_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_doctor_ratings_clinic_id", table_name="doctor_ratings")
    op.drop_index("ix_doctor_ratings_doctor_id", table_name="doctor_ratings")
    op.drop_index("ix_doctor_ratings_patient_id", table_name="doctor_ratings")
    op.drop_index(
        "ix_doctor_ratings_appointment_id", table_name="doctor_ratings"
    )
    op.drop_table("doctor_ratings")
