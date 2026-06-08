"""add prescription revision system

Revision ID: c9ce1c126b4a
Revises: ff7c13fae0c3
Create Date: 2026-05-27 23:15:49.074719

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9ce1c126b4a'
down_revision: Union[str, Sequence[str], None] = 'ff7c13fae0c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ====================================
    # ADD ENUM VALUE
    # ====================================

    op.execute(
        "ALTER TYPE prescriptionstatus "
        "ADD VALUE IF NOT EXISTS 'SUPERSEDED'"
    )

    # ====================================
    # ADD COLUMNS
    # ====================================

    op.add_column(
        "prescriptions",
        sa.Column(
            "parent_prescription_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "prescriptions",
        sa.Column(
            "revision_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.add_column(
        "prescriptions",
        sa.Column(
            "is_latest_revision",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )

    # ====================================
    # FOREIGN KEY
    # ====================================

    op.create_foreign_key(
        "fk_prescriptions_parent",
        "prescriptions",
        "prescriptions",
        ["parent_prescription_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ====================================
    # INDEXES
    # ====================================

    op.create_index(
        "ix_prescriptions_parent_prescription_id",
        "prescriptions",
        ["parent_prescription_id"],
    )


def downgrade() -> None:

    op.drop_index(
        "ix_prescriptions_parent_prescription_id",
        table_name="prescriptions",
    )

    op.drop_constraint(
        "fk_prescriptions_parent",
        "prescriptions",
        type_="foreignkey",
    )

    op.drop_column(
        "prescriptions",
        "is_latest_revision",
    )

    op.drop_column(
        "prescriptions",
        "revision_number",
    )

    op.drop_column(
        "prescriptions",
        "parent_prescription_id",
    )