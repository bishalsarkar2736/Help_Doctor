"""create medicine_assistant_queries table

Revision ID: 7ecb444a86ad
Revises: 46510764fea3
Create Date: 2026-06-05 11:42:40.893166

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ecb444a86ad'
down_revision: Union[str, Sequence[str], None] = '46510764fea3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.create_table(
        "medicine_assistant_queries",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),

        sa.Column(
            "question",
            sa.String(length=1000),
            nullable=False,
        ),

        sa.Column(
            "medicine_name",
            sa.String(length=255),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
        ),
    )

    op.create_index(
        "ix_medicine_assistant_queries_medicine_name",
        "medicine_assistant_queries",
        ["medicine_name"],
        unique=False,
    )


def downgrade():

    op.drop_index(
        "ix_medicine_assistant_queries_medicine_name",
        table_name="medicine_assistant_queries",
    )

    op.drop_table(
        "medicine_assistant_queries"
    )