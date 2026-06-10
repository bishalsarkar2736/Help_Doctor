"""create medicine_ai_logs table

Revision ID: 93ff4a2c3800
Revises: b8786f83edbb
Create Date: 2026-06-09 18:18:54.187444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '93ff4a2c3800'
down_revision: Union[str, Sequence[str], None] = 'b8786f83edbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "medicine_ai_logs",

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
                ondelete="SET NULL",
            ),
            nullable=True,
        ),

        sa.Column(
            "medicine_name",
            sa.String(length=255),
            nullable=True,
        ),

        sa.Column(
            "question",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "answer",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "prompt_version",
            sa.String(length=50),
            nullable=False,
        ),

        sa.Column(
            "tokens_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),

        sa.Column(
            "latency_ms",
            sa.Integer(),
            nullable=False,
            server_default="0",
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
        "ix_medicine_ai_logs_medicine_id",
        "medicine_ai_logs",
        ["medicine_id"],
    )

    op.create_index(
        "ix_medicine_ai_logs_created_at",
        "medicine_ai_logs",
        ["created_at"],
    )

    op.create_index(
        "ix_medicine_ai_logs_medicine_name",
        "medicine_ai_logs",
        ["medicine_name"],
    )

    op.create_index(
        "ix_medicine_ai_logs_prompt_version",
        "medicine_ai_logs",
        ["prompt_version"],
    )


def downgrade() -> None:

    op.drop_index(
        "ix_medicine_ai_logs_prompt_version",
        table_name="medicine_ai_logs",
    )

    op.drop_index(
        "ix_medicine_ai_logs_medicine_name",
        table_name="medicine_ai_logs",
    )

    op.drop_index(
        "ix_medicine_ai_logs_created_at",
        table_name="medicine_ai_logs",
    )

    op.drop_index(
        "ix_medicine_ai_logs_medicine_id",
        table_name="medicine_ai_logs",
    )

    op.drop_table(
        "medicine_ai_logs"
    )
