"""create medicine aliases table

Revision ID: b8786f83edbb
Revises: 7ecb444a86ad
Create Date: 2026-06-06 14:54:12.318568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8786f83edbb'
down_revision: Union[str, Sequence[str], None] = '7ecb444a86ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "medicine_aliases",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),

        sa.Column(
            "medicine_id",
            sa.Integer(),
            sa.ForeignKey(
                "medicines.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),

        sa.Column(
            "alias",
            sa.String(length=255),
            nullable=False,
        ),

        sa.UniqueConstraint(
            "medicine_id",
            "alias",
            name=(
                "uq_medicine_aliases_"
                "medicine_id_alias"
            ),
        ),
    )

    op.create_index(
        "ix_medicine_aliases_medicine_id",
        "medicine_aliases",
        ["medicine_id"],
        unique=False,
    )

    op.create_index(
        "ix_medicine_aliases_alias",
        "medicine_aliases",
        ["alias"],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "ix_medicine_aliases_alias",
        table_name="medicine_aliases",
    )

    op.drop_index(
        "ix_medicine_aliases_medicine_id",
        table_name="medicine_aliases",
    )

    op.drop_table(
        "medicine_aliases"
    )