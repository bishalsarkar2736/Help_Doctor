"""add gateway payment uniqueness

Revision ID: df60e96699e9
Revises: ccf4b885e9cf
Create Date: 2026-06-23 19:59:16.937766

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'df60e96699e9'
down_revision: Union[str, Sequence[str], None] = 'ccf4b885e9cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    # remove redundant index
    op.drop_index(
        "idx_payment_transaction",
        table_name="payments",
    )

    # add unique constraint
    op.create_unique_constraint(
        "uq_gateway_payment",
        "payments",
        ["gateway_payment_id"],
    )


def downgrade():

    op.drop_constraint(
        "uq_gateway_payment",
        "payments",
        type_="unique",
    )

    op.create_index(
        "idx_payment_transaction",
        "payments",
        ["transaction_id"],
        unique=False,
    )