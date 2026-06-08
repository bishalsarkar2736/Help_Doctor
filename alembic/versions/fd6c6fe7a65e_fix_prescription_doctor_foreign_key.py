"""fix prescription doctor foreign key

Revision ID: fd6c6fe7a65e
Revises: 2dab2b9ba8f4
Create Date: 2026-05-19 16:20:29.325362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd6c6fe7a65e'
down_revision: Union[str, Sequence[str], None] = '2dab2b9ba8f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ====================================
    # DROP OLD FK -> users.id
    # ====================================

    op.drop_constraint(
        "prescriptions_doctor_id_fkey",
        "prescriptions",
        type_="foreignkey",
    )

    # ====================================
    # CREATE NEW FK -> doctors.id
    # ====================================

    op.create_foreign_key(
        "prescriptions_doctor_id_fkey",
        "prescriptions",
        "doctors",
        ["doctor_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:

    # ====================================
    # DROP FK -> doctors.id
    # ====================================

    op.drop_constraint(
        "prescriptions_doctor_id_fkey",
        "prescriptions",
        type_="foreignkey",
    )

    # ====================================
    # RESTORE FK -> users.id
    # ====================================

    op.create_foreign_key(
        "prescriptions_doctor_id_fkey",
        "prescriptions",
        "users",
        ["doctor_id"],
        ["id"],
        ondelete="CASCADE",
    )
