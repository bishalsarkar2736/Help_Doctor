"""add prescription system

Revision ID: 2256acdf5ed1
Revises: bf893207751b
Create Date: 2026-03-10 23:03:09.384289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2256acdf5ed1'
down_revision: Union[str, Sequence[str], None] = 'bf893207751b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "prescriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appointment_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doctor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "prescription_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prescription_id", sa.Integer(), nullable=False),
        sa.Column("medicine_name", sa.String(length=255), nullable=False),
        sa.Column("dosage", sa.String(length=100), nullable=True),
        sa.Column("frequency", sa.String(length=100), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["prescription_id"],
            ["prescriptions.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_prescriptions_patient_id",
        "prescriptions",
        ["patient_id"],
    )

def downgrade() -> None:

    op.drop_index("ix_prescriptions_patient_id", table_name="prescriptions")

    op.drop_table("prescription_items")

    op.drop_table("prescriptions")
