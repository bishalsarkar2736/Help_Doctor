"""add public invoice id to payments

Revision ID: 7487467fb2f7
Revises: eba4f4e128ce
Create Date: 2026-06-24 22:52:22.202676

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7487467fb2f7'
down_revision: Union[str, Sequence[str], None] = 'eba4f4e128ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.add_column(
        "payments",
        sa.Column(
            "public_invoice_id",
            sa.String(length=36),
            nullable=True,
        ),
    )

    op.create_unique_constraint(
        "uq_payments_public_invoice_id",
        "payments",
        ["public_invoice_id"],
    )


def downgrade():

    op.drop_constraint(
        "uq_payments_public_invoice_id",
        "payments",
        type_="unique",
    )

    op.drop_column(
        "payments",
        "public_invoice_id",
    )