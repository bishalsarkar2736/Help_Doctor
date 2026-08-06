"""other names for the same active substance

Revision ID: a9f47c2b3e61
Revises: c3e58a17f9d2

Aliases existed only per brand, so there was nowhere to record that
Acetaminophen and Paracetamol are the same substance. That fact belongs to the
substance: filing it against one brand would mean repeating it on every
Paracetamol product and losing it on the next one added.

The gap it closes is a patient whose allergy is written under a name the
catalogue does not use. "Acetaminophen" in an allergy field matches nothing
today, because every brand of it is filed under Paracetamol.

Empty on creation. Aliases are clinical claims about which names denote the
same substance, and inventing them from string similarity is exactly the kind
of guess that could attach the wrong substance to a prescription.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9f47c2b3e61"
down_revision: Union[str, Sequence[str], None] = "c3e58a17f9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generic_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generic_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["generic_id"],
            ["generics.id"],
            # CASCADE: an alias is meaningless without the substance it names.
            # Unlike medicines.generic_id, nothing clinical is lost by removing
            # it — the prescription records the medicine, not the alias.
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "generic_id",
            "normalized_alias",
            name="uq_generic_aliases_generic_id_normalized_alias",
        ),
    )
    op.create_index(
        "ix_generic_aliases_generic_id", "generic_aliases", ["generic_id"]
    )
    # The allergy check reads this on every prescription, so the lookup is an
    # indexed equality test rather than a scan over the alias list.
    op.create_index(
        "ix_generic_aliases_normalized_alias",
        "generic_aliases",
        ["normalized_alias"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generic_aliases_normalized_alias", table_name="generic_aliases"
    )
    op.drop_index("ix_generic_aliases_generic_id", table_name="generic_aliases")
    op.drop_table("generic_aliases")
