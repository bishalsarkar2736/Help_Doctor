"""clinic opening hours and holiday schedule

Revision ID: d5b83f1a7c40
Revises: a9f47c2b3e61

The scheduling assistant is asked "are you open now?" and "are you open on
Friday?", and nothing in the schema could answer either. A clinic carried a
timezone and an address but no hours.

JSON rather than normalized tables. These are always read whole, for one
clinic, to answer one question — never joined, never filtered across clinics —
and a weekday can hold several ranges because a clinic that closes for lunch is
the normal case here, not an edge case. A row-per-range table would buy
queries nobody makes and cost a join on every read.

Both default to empty rather than to invented hours. A clinic that has not set
its hours must produce "I don't have opening hours for this clinic" — assuming
nine-to-five would have the assistant state something no one entered.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5b83f1a7c40"
down_revision: Union[str, Sequence[str], None] = "a9f47c2b3e61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clinics",
        sa.Column(
            "opening_hours",
            sa.JSON(),
            nullable=False,
            # Server default so existing rows land on "no hours recorded"
            # rather than NULL, which every reader would have to special-case.
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "clinics",
        sa.Column(
            "holiday_schedule",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("clinics", "holiday_schedule")
    op.drop_column("clinics", "opening_hours")
