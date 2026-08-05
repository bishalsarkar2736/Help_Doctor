"""keep the allergy override justification on the prescription

Revision ID: c3e58a17f9d2
Revises: b7c94e21d5a8

The reason a prescriber went through an allergy warning lived only in the audit
log. That trail is append-only and subject to PHI retention purging, so using
it to decide whether a fresh justification is needed would tie a safety rule to
log retention. It also meant the clinical record itself did not say why the
warning was overridden.

Substances rather than typed medicine names, because relabelling a line or
switching to another brand of the same generic is not a new clinical decision.

NOT backfilled. Prescriptions overridden before this migration have their
reason in the audit log only, and copying it across would be reconstructing a
clinical justification rather than recording one. Those prescriptions simply
prompt for a fresh reason on the next edit, which fails safe.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e58a17f9d2"
down_revision: Union[str, Sequence[str], None] = "b7c94e21d5a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prescriptions",
        sa.Column("allergy_override_reason", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "prescriptions",
        sa.Column("allergy_override_substances", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prescriptions", "allergy_override_substances")
    op.drop_column("prescriptions", "allergy_override_reason")
