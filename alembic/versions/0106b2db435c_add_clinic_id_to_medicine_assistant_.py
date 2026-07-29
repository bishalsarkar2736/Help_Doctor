"""add clinic_id to medicine_assistant_queries

Revision ID: 0106b2db435c
Revises: cf88ffce4077
Create Date: 2026-07-10 14:24:53.342697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0106b2db435c'
down_revision: Union[str, Sequence[str], None] = 'cf88ffce4077'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.add_column(
        "medicine_assistant_queries",
        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_medicine_assistant_queries_clinic_id",
        "medicine_assistant_queries",
        ["clinic_id"],
    )

    op.create_foreign_key(
        "fk_medicine_assistant_queries_clinic_id",
        "medicine_assistant_queries",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade():

    op.drop_constraint(
        "fk_medicine_assistant_queries_clinic_id",
        "medicine_assistant_queries",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_medicine_assistant_queries_clinic_id",
        table_name="medicine_assistant_queries",
    )

    op.drop_column(
        "medicine_assistant_queries",
        "clinic_id",
    )