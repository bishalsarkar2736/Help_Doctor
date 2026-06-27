"""add refund fields to payments

Revision ID: 5dcf7de83d71
Revises: 7487467fb2f7
Create Date: 2026-06-25 11:04:07.478153

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dcf7de83d71'
down_revision: Union[str, Sequence[str], None] = '7487467fb2f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.add_column(
        "payments",
        sa.Column(
            "refunded_amount",
            sa.Numeric(10, 2),
            nullable=True,
        ),
    )

    op.add_column(
        "payments",
        sa.Column(
            "refunded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "payments",
        sa.Column(
            "refund_transaction_id",
            sa.String(100),
            nullable=True,
        ),
    )

    op.create_unique_constraint(
        "uq_payments_refund_transaction_id",
        "payments",
        ["refund_transaction_id"],
    )


def downgrade():

    op.drop_constraint(
        "uq_payments_refund_transaction_id",
        "payments",
        type_="unique",
    )

    op.drop_column(
        "payments",
        "refund_transaction_id",
    )

    op.drop_column(
        "payments",
        "refunded_at",
    )

    op.drop_column(
        "payments",
        "refunded_amount",
    )
