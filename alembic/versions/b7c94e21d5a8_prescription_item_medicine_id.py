"""link prescription items to the medicine catalogue

Revision ID: b7c94e21d5a8
Revises: f1d3b8a52c94

Prescribing is free text: the doctor types a name and everything downstream has
to guess which catalogue row was meant. Recording the picked medicine removes
the guess from the allergy check, which is the one place guessing is unsafe.

Deliberately NOT backfilled. Matching historical rows by name would attach a
catalogue link that the prescriber never actually chose, and a wrong link is
worse than no link — it would state that a specific substance was prescribed on
the strength of a string comparison. Old rows keep medicine_id NULL and fall
back to name matching, exactly as they do today.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c94e21d5a8"
down_revision: Union[str, Sequence[str], None] = "f1d3b8a52c94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prescription_items",
        sa.Column("medicine_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_prescription_items_medicine_id",
        "prescription_items",
        ["medicine_id"],
    )
    op.create_foreign_key(
        "fk_prescription_items_medicine_id",
        "prescription_items",
        "medicines",
        ["medicine_id"],
        ["id"],
        # SET NULL, not RESTRICT: a prescription is a clinical record and must
        # outlive the catalogue row it referenced. medicine_name still holds
        # what was prescribed, so the record stays complete.
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_prescription_items_medicine_id",
        "prescription_items",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_prescription_items_medicine_id",
        table_name="prescription_items",
    )
    op.drop_column("prescription_items", "medicine_id")
