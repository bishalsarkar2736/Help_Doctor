"""add payment audit logs

Revision ID: 80681b1112b2
Revises: 80e42bf37663
Create Date: 2026-03-12 15:24:17.158386

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '80681b1112b2'
down_revision: Union[str, Sequence[str], None] = '80e42bf37663'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.create_table(
        "payment_audit_logs",

        sa.Column("id", sa.Integer(), primary_key=True),

        sa.Column(
            "payment_id",
            sa.Integer(),
            sa.ForeignKey("payments.id", ondelete="CASCADE"),
        ),

        sa.Column("gateway", sa.String(length=20)),

        sa.Column("event_type", sa.String(length=50)),

        sa.Column("payload", sa.JSON()),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade():

    op.drop_table("payment_audit_logs")