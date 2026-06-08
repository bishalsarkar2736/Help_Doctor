"""doctor professional identity

Revision ID: de8f23c973a2
Revises: e7bc550f31a2
Create Date: 2026-05-30 21:31:37.848845

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de8f23c973a2'
down_revision: Union[str, Sequence[str], None] = 'e7bc550f31a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.add_column(
        "doctors",
        sa.Column(
            "qualification",
            sa.String(length=200),
            nullable=True,
        ),
    )

    op.add_column(
        "doctors",
        sa.Column(
            "medical_registration_number",
            sa.String(length=100),
            nullable=True,
        ),
    )

    op.add_column(
        "doctors",
        sa.Column(
            "signature_file_path",
            sa.String(length=500),
            nullable=True,
        ),
    )

    op.add_column(
        "doctors",
        sa.Column(
            "signature_uploaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_unique_constraint(
        "uq_doctors_medical_registration_number",
        "doctors",
        ["medical_registration_number"],
    )


def downgrade() -> None:

    op.drop_constraint(
        "uq_doctors_medical_registration_number",
        "doctors",
        type_="unique",
    )

    op.drop_column(
        "doctors",
        "signature_uploaded_at",
    )

    op.drop_column(
        "doctors",
        "signature_file_path",
    )

    op.drop_column(
        "doctors",
        "medical_registration_number",
    )

    op.drop_column(
        "doctors",
        "qualification",
    )
