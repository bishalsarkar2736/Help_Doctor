"""create audit_logs table

Revision ID: 01de1781f7a9
Revises: 07aeb0972860
Create Date: 2026-03-06 20:49:01.459340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01de1781f7a9'
down_revision: Union[str, Sequence[str], None] = '07aeb0972860'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=50)),
        sa.Column("resource", sa.String(length=100)),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("details", sa.JSON()),
        sa.Column("request_id", sa.String(length=100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    op.create_index(
        "ix_audit_logs_user_id",
        "audit_logs",
        ["user_id"],
    )


def downgrade():
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")
