"""create medicine ai feedback table

Revision ID: 99e77938e0ac
Revises: 8d81da644fe2
Create Date: 2026-06-10 10:39:38.772403

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '99e77938e0ac'
down_revision: Union[str, Sequence[str], None] = '8d81da644fe2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "medicine_ai_feedback",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "ai_log_id",
            sa.Integer(),
            sa.ForeignKey(
                "medicine_ai_logs.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "helpful",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "ai_log_id",
            name="uq_medicine_ai_feedback_ai_log_id",
        ),
    )

    op.create_index(
        "ix_medicine_ai_feedback_ai_log_id",
        "medicine_ai_feedback",
        ["ai_log_id"],
    )


def downgrade() -> None:

    op.drop_index(
        "ix_medicine_ai_feedback_ai_log_id",
        table_name="medicine_ai_feedback",
    )

    op.drop_table(
        "medicine_ai_feedback",
    )