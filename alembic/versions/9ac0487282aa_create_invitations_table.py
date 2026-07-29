"""create invitations table

Revision ID: 9ac0487282aa
Revises: 50540e90b6d4
Create Date: 2026-07-23 12:41:48.223346

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9ac0487282aa'
down_revision: Union[str, Sequence[str], None] = '50540e90b6d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New enum type for invitation status.
invitation_status_enum = postgresql.ENUM(
    "PENDING", "ACCEPTED", "REVOKED",
    name="invitation_status",
    create_type=False,
)

# Existing enum type (already created for users.role) — reused, not created.
user_roles_enum = postgresql.ENUM(
    "SUPER_ADMIN", "ADMIN", "DOCTOR", "RECEPTIONIST", "PATIENT",
    name="user_roles",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    invitation_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", user_roles_enum, nullable=False),
        sa.Column(
            "clinic_id",
            sa.Integer(),
            sa.ForeignKey("clinics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            invitation_status_enum,
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "invited_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "accepted_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )

    op.create_index("ix_invitations_email", "invitations", ["email"])
    op.create_index("ix_invitations_clinic_id", "invitations", ["clinic_id"])
    op.create_index("ix_invitations_status", "invitations", ["status"])
    op.create_index(
        "ix_invitations_token_hash", "invitations", ["token_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.drop_index("ix_invitations_status", table_name="invitations")
    op.drop_index("ix_invitations_clinic_id", table_name="invitations")
    op.drop_index("ix_invitations_email", table_name="invitations")
    op.drop_table("invitations")

    bind = op.get_bind()
    invitation_status_enum.drop(bind, checkfirst=True)
