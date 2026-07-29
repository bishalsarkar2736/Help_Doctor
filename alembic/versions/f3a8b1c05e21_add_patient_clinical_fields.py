"""add patient clinical fields

Revision ID: f3a8b1c05e21
Revises: e7c1a9d4f2b0
Create Date: 2026-07-26 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a8b1c05e21"
down_revision: Union[str, Sequence[str], None] = "e7c1a9d4f2b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("allergies", sa.Text(), nullable=True))
    op.add_column("patients", sa.Column("current_medications", sa.Text(), nullable=True))
    op.add_column("patients", sa.Column("chronic_conditions", sa.Text(), nullable=True))
    op.add_column("patients", sa.Column("blood_type", sa.String(length=8), nullable=True))
    op.add_column("patients", sa.Column("emergency_contact_name", sa.String(length=120), nullable=True))
    op.add_column("patients", sa.Column("emergency_contact_phone", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("patients", "emergency_contact_phone")
    op.drop_column("patients", "emergency_contact_name")
    op.drop_column("patients", "blood_type")
    op.drop_column("patients", "chronic_conditions")
    op.drop_column("patients", "current_medications")
    op.drop_column("patients", "allergies")
