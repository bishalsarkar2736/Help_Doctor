"""add prescription status and indexes

Revision ID: 2dab2b9ba8f4
Revises: d38507eff42c
Create Date: 2026-05-17 22:11:45.666264

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2dab2b9ba8f4'
down_revision: Union[str, Sequence[str], None] = 'd38507eff42c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # =====================================================
    # Create PostgreSQL enum
    # =====================================================
    op.execute(
        """
        CREATE TYPE prescriptionstatus AS ENUM (
            'DRAFT',
            'ISSUED',
            'REVOKED'
        )
        """
    )

    # =====================================================
    # Add status column
    # =====================================================
    op.add_column(
        "prescriptions",
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "ISSUED",
                "REVOKED",
                name="prescriptionstatus",
            ),
            nullable=False,
            server_default="DRAFT",
        ),
    )

    # =====================================================
    # Add issued_at column
    # =====================================================
    op.add_column(
        "prescriptions",
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # =====================================================
    # Missing indexes only
    # patient_id already exists
    # =====================================================
    op.create_index(
        "ix_prescriptions_appointment_id",
        "prescriptions",
        ["appointment_id"],
        unique=False,
    )

    op.create_index(
        "ix_prescriptions_doctor_id",
        "prescriptions",
        ["doctor_id"],
        unique=False,
    )

    # remove temporary default
    op.alter_column(
        "prescriptions",
        "status",
        server_default=None,
    )


def downgrade() -> None:

    op.drop_index(
        "ix_prescriptions_doctor_id",
        table_name="prescriptions",
    )

    op.drop_index(
        "ix_prescriptions_appointment_id",
        table_name="prescriptions",
    )

    op.drop_column(
        "prescriptions",
        "issued_at",
    )

    op.drop_column(
        "prescriptions",
        "status",
    )

    op.execute(
        "DROP TYPE prescriptionstatus"
    )