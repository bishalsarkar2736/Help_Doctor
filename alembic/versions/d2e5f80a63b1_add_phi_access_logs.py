"""add phi_access_logs

Records READS of protected health information. The existing audit_logs table
covers mutations, which by definition cannot show that a clinician opened a
patient record and changed nothing — the access that compliance regimes most
want evidence of.

Foreign keys are RESTRICT, not CASCADE: an access record must outlive the
account that made it. Deleting a user must never erase the evidence of what
that user read.

Revision ID: d2e5f80a63b1
Revises: c8f13b7a904e
Create Date: 2026-07-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e5f80a63b1"
down_revision: Union[str, Sequence[str], None] = "c8f13b7a904e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "phi_access_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_role", sa.String(length=20), nullable=False),
        sa.Column("clinic_id", sa.Integer(), nullable=True),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_phi_access_logs_actor_user_id", "phi_access_logs", ["actor_user_id"]
    )
    op.create_index(
        "ix_phi_access_logs_request_id", "phi_access_logs", ["request_id"]
    )
    op.create_index(
        "ix_phi_access_logs_created_at", "phi_access_logs", ["created_at"]
    )

    # Composite indexes for the three questions that actually get asked:
    #   who touched this patient / what did this actor touch / clinic-wide review
    op.create_index(
        "ix_phi_access_patient_time",
        "phi_access_logs",
        ["patient_id", "created_at"],
    )
    op.create_index(
        "ix_phi_access_actor_time",
        "phi_access_logs",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_phi_access_clinic_time",
        "phi_access_logs",
        ["clinic_id", "created_at"],
    )


def downgrade() -> None:
    for name in (
        "ix_phi_access_clinic_time",
        "ix_phi_access_actor_time",
        "ix_phi_access_patient_time",
        "ix_phi_access_logs_created_at",
        "ix_phi_access_logs_request_id",
        "ix_phi_access_logs_actor_user_id",
    ):
        op.drop_index(name, table_name="phi_access_logs")

    op.drop_table("phi_access_logs")
