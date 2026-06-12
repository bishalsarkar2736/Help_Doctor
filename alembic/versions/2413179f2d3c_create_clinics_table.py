"""create clinics table

Revision ID: 2413179f2d3c
Revises: 99e77938e0ac
Create Date: 2026-06-10 19:52:15.488667

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2413179f2d3c'
down_revision: Union[str, Sequence[str], None] = '99e77938e0ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.create_table(
        "clinics",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),

        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
        ),

        sa.Column(
            "logo_url",
            sa.String(length=500),
            nullable=True,
        ),

        sa.Column(
            "address",
            sa.String(length=500),
            nullable=True,
        ),

        sa.Column(
            "phone",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "email",
            sa.String(length=255),
            nullable=True,
        ),

        sa.Column(
            "website",
            sa.String(length=255),
            nullable=True,
        ),

        sa.Column(
            "primary_color",
            sa.String(length=20),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_clinics_name",
        "clinics",
        ["name"],
    )


def downgrade():

    op.drop_index(
        "ix_clinics_name",
        table_name="clinics",
    )

    op.drop_table("clinics")
