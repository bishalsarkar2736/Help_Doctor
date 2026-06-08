"""add medicines table

Revision ID: 46510764fea3
Revises: 6b6b946f7dcd
Create Date: 2026-06-04 12:01:22.683394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '46510764fea3'
down_revision: Union[str, Sequence[str], None] = '6b6b946f7dcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.create_table(
        "medicines",

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
            "generic_name",
            sa.String(length=255),
            nullable=False,
        ),

        sa.Column(
            "strength",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "manufacturer",
            sa.String(length=255),
            nullable=False,
        ),

        sa.Column(
            "category",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "dosage_form",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "common_use",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "common_side_effects",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "storage_guidance",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "is_brand",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_index(
        "ix_medicines_name",
        "medicines",
        ["name"],
        unique=True,
    )

    op.create_index(
        "ix_medicines_generic_name",
        "medicines",
        ["generic_name"],
        unique=False,
    )

    op.create_index(
        "ix_medicines_strength",
        "medicines",
        ["strength"],
        unique=False,
    )

    op.create_index(
        "ix_medicines_manufacturer",
        "medicines",
        ["manufacturer"],
        unique=False,
    )


def downgrade():

    op.drop_index(
        "ix_medicines_manufacturer",
        table_name="medicines",
    )

    op.drop_index(
        "ix_medicines_generic_name",
        table_name="medicines",
    )

    op.drop_index(
        "ix_medicines_name",
        table_name="medicines",
    )

    op.drop_index(
        "ix_medicines_strength",
        table_name="medicines",
    )

    op.drop_table("medicines")