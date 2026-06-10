"""create medicine_ai_error_logs table

Revision ID: 8d81da644fe2
Revises: 93ff4a2c3800
Create Date: 2026-06-09 23:37:51.499647

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d81da644fe2'
down_revision: Union[str, Sequence[str], None] = '93ff4a2c3800'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "medicine_ai_error_logs",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),

        sa.Column(
            "question",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "medicine_name",
            sa.String(length=255),
            nullable=True,
        ),

        sa.Column(
            "error",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_medicine_ai_error_logs_created_at",
        "medicine_ai_error_logs",
        ["created_at"],
    )

    op.create_index(
        "ix_medicine_ai_error_logs_medicine_name",
        "medicine_ai_error_logs",
        ["medicine_name"],
    )


def downgrade() -> None:

    op.drop_index(
        "ix_medicine_ai_error_logs_medicine_name",
        table_name="medicine_ai_error_logs",
    )

    op.drop_index(
        "ix_medicine_ai_error_logs_created_at",
        table_name="medicine_ai_error_logs",
    )

    op.drop_table(
        "medicine_ai_error_logs"
    )