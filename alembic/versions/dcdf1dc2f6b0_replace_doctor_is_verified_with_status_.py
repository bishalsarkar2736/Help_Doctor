"""replace doctor is_verified with status enum

Revision ID: dcdf1dc2f6b0
Revises: 9ac0487282aa
Create Date: 2026-07-23 12:54:42.582599

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'dcdf1dc2f6b0'
down_revision: Union[str, Sequence[str], None] = '9ac0487282aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


doctor_status_enum = postgresql.ENUM(
    "PENDING", "APPROVED", "REJECTED", "SUSPENDED",
    name="doctor_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    doctor_status_enum.create(bind, checkfirst=True)

    # New status column (nullable during backfill).
    op.add_column(
        "doctors",
        sa.Column("status", doctor_status_enum, nullable=True),
    )

    # Audit columns.
    op.add_column(
        "doctors",
        sa.Column(
            "approved_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "doctors",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "doctors",
        sa.Column(
            "rejected_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "doctors",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "doctors",
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
    )

    # Backfill status from the old boolean, then preserve an approval timestamp.
    op.execute(
        "UPDATE doctors SET status = "
        "(CASE WHEN is_verified THEN 'APPROVED' ELSE 'PENDING' END)"
        "::doctor_status"
    )
    op.execute(
        "UPDATE doctors SET approved_at = created_at WHERE status = 'APPROVED'"
    )

    # Lock the column down.
    op.alter_column(
        "doctors",
        "status",
        nullable=False,
        server_default="PENDING",
    )
    op.create_index("ix_doctors_status", "doctors", ["status"])

    # Drop the old boolean — status is now the single source of truth.
    op.drop_column("doctors", "is_verified")


def downgrade() -> None:
    op.add_column(
        "doctors",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        "UPDATE doctors SET is_verified = (status = 'APPROVED')"
    )

    op.drop_index("ix_doctors_status", table_name="doctors")
    op.drop_column("doctors", "rejection_reason")
    op.drop_column("doctors", "rejected_at")
    op.drop_column("doctors", "rejected_by")
    op.drop_column("doctors", "approved_at")
    op.drop_column("doctors", "approved_by")
    op.drop_column("doctors", "status")

    bind = op.get_bind()
    doctor_status_enum.drop(bind, checkfirst=True)
