"""add prescription uuid

Revision ID: ff7c13fae0c3
Revises: fd6c6fe7a65e
Create Date: 2026-05-27 18:17:45.785706

"""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ff7c13fae0c3'
down_revision: Union[str, Sequence[str], None] = 'fd6c6fe7a65e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ====================================
    # ADD UUID COLUMN (nullable first)
    # ====================================

    op.add_column(
        "prescriptions",
        sa.Column(
            "uuid",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # ====================================
    # BACKFILL EXISTING ROWS
    # ====================================

    connection = op.get_bind()

    prescriptions = connection.execute(
        sa.text(
            """
            SELECT id
            FROM prescriptions
            """
        )
    ).fetchall()

    for row in prescriptions:

        connection.execute(
            sa.text(
                """
                UPDATE prescriptions
                SET uuid = :uuid
                WHERE id = :id
                """
            ),
            {
                "uuid": str(uuid.uuid4()),
                "id": row.id,
            },
        )

    # ====================================
    # SET NOT NULL
    # ====================================

    op.alter_column(
        "prescriptions",
        "uuid",
        nullable=False,
    )

    # ====================================
    # ADD UNIQUE INDEX
    # ====================================

    op.create_index(
        op.f("ix_prescriptions_uuid"),
        "prescriptions",
        ["uuid"],
        unique=True,
    )


def downgrade() -> None:

    # ====================================
    # DROP INDEX
    # ====================================

    op.drop_index(
        op.f("ix_prescriptions_uuid"),
        table_name="prescriptions",
    )

    # ====================================
    # DROP COLUMN
    # ====================================

    op.drop_column(
        "prescriptions",
        "uuid",
    )