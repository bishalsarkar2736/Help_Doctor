"""add notification category

Revision ID: c93c19a0b266
Revises: 8efbb07d3104
Create Date: 2026-06-16 00:55:25.457238

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c93c19a0b266'
down_revision: Union[str, Sequence[str], None] = '8efbb07d3104'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


notification_category = sa.Enum(
    "APPOINTMENT",
    "PRESCRIPTION",
    "PAYMENT",
    "SYSTEM",
    name="notification_category",
)


def upgrade():

    bind = op.get_bind()

    notification_category.create(
        bind,
        checkfirst=True,
    )

    op.add_column(
        "notifications",
        sa.Column(
            "category",
            notification_category,
            nullable=False,
            server_default="SYSTEM",
        ),
    )

    # remove default immediately
    op.alter_column(
        "notifications",
        "category",
        server_default=None,
    )


def downgrade():

    op.drop_column(
        "notifications",
        "category",
    )

    notification_category.drop(
        op.get_bind(),
        checkfirst=True,
    )