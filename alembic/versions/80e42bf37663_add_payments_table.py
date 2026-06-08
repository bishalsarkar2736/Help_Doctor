"""add payments table

Revision ID: 80e42bf37663
Revises: 2256acdf5ed1
Create Date: 2026-03-11 15:29:51.602827

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80e42bf37663'
down_revision: Union[str, Sequence[str], None] = '2256acdf5ed1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),

        sa.Column(
            "appointment_id",
            sa.Integer(),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column(
            "amount",
            sa.Numeric(10, 2),
            nullable=False,
        ),

        sa.Column(
            "currency",
            sa.String(10),
            nullable=False,
            server_default="BDT",
        ),

        sa.Column(
            "method",
            sa.String(20),
            nullable=False,
        ),

        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
        ),

        sa.Column(
            "transaction_id",
            sa.String(100),
            unique=True,
            nullable=True,
        ),

        sa.Column(
            "gateway_payment_id",
            sa.String(100),
            nullable=True,
        ),

        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "idx_payment_status",
        "payments",
        ["status"],
    )

    op.create_index(
        "idx_payment_transaction",
        "payments",
        ["transaction_id"],
    )


def downgrade() -> None:

    op.drop_index("idx_payment_transaction", table_name="payments")
    op.drop_index("idx_payment_status", table_name="payments")

    op.drop_table("payments")
