"""add clinic status lifecycle

Revision ID: fbf361fb7bd6
Revises: dcdf1dc2f6b0
Create Date: 2026-07-23 20:16:37.280259

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fbf361fb7bd6'
down_revision: Union[str, Sequence[str], None] = 'dcdf1dc2f6b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


clinic_status_enum = postgresql.ENUM(
    "ACTIVE", "SUSPENDED", "DELETED",
    name="clinic_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    clinic_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "clinics",
        sa.Column(
            "status",
            clinic_status_enum,
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.add_column(
        "clinics",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "clinics",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_clinics_status", "clinics", ["status"])


def downgrade() -> None:
    op.drop_index("ix_clinics_status", table_name="clinics")
    op.drop_column("clinics", "deleted_at")
    op.drop_column("clinics", "suspended_at")
    op.drop_column("clinics", "status")

    bind = op.get_bind()
    clinic_status_enum.drop(bind, checkfirst=True)
