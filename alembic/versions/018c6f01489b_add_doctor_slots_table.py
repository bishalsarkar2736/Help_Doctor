"""add doctor_slots table

Revision ID: 018c6f01489b
Revises: eaabd6b7e65b
Create Date: 2026-03-17 11:12:31.571541

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '018c6f01489b'
down_revision: Union[str, Sequence[str], None] = 'eaabd6b7e65b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.create_table(
        "doctor_slots",
        sa.Column("id", sa.Integer(), primary_key=True),

        sa.Column(
            "doctor_id",
            sa.Integer(),
            sa.ForeignKey("doctors.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),

        sa.Column("is_booked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # index for fast lookup
    op.create_index(
        "idx_doctor_slot_doctor_time",
        "doctor_slots",
        ["doctor_id", "start_time"],
    )

    # 🔒 critical: prevent duplicate slots
    op.create_index(
        "uq_doctor_slot_unique",
        "doctor_slots",
        ["doctor_id", "start_time"],
        unique=True,
    )


def downgrade():

    op.drop_index("uq_doctor_slot_unique", table_name="doctor_slots")
    op.drop_index("idx_doctor_slot_doctor_time", table_name="doctor_slots")
    op.drop_table("doctor_slots")
