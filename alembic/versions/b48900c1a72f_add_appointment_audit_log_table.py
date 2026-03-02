"""add appointment audit log table

Revision ID: b48900c1a72f
Revises: f593ef7da81c
Create Date: 2026-02-17 21:12:43.208431

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b48900c1a72f'
down_revision: Union[str, Sequence[str], None] = 'f593ef7da81c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "appointment_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "appointment_id",
            sa.BigInteger(),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("changed_by", sa.BigInteger(), nullable=False),
        sa.Column("actor_role", sa.String(length=16), nullable=False),
        sa.Column("is_idempotent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_appointment_audit_log_appointment_id",
        "appointment_audit_log",
        ["appointment_id"],
    )


def downgrade():
    op.drop_table("appointment_audit_log")
