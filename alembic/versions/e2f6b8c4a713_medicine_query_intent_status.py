"""record what was asked for and how it went, not what was said

Revision ID: e2f6b8c4a713
Revises: c4a71e93d05b

The question text was removed in c4a71e93d05b, which left the log able to say
only which medicine was matched. These two columns restore the operational
picture without restoring the words:

  intent  - which of the supported questions was asked
  status  - ok, not_found, ambiguous, field_missing, refused, unknown

Between them they answer what the removed text was really being read for. How
often are we refusing? Which fields are asked for and empty? Is a rising
not_found rate a gap in the catalogue or in its aliases? None of that needs
anyone's sentence.

Both are nullable because v1 writes neither, and the two assistants log to the
same table while they run side by side.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f6b8c4a713"
down_revision: Union[str, Sequence[str], None] = "c4a71e93d05b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "medicine_assistant_queries",
        sa.Column("intent", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "medicine_assistant_queries",
        sa.Column("status", sa.String(length=20), nullable=True),
    )
    # Reporting groups by these two and by nothing else, so one index covering
    # both serves every query the analytics make.
    op.create_index(
        "ix_medicine_assistant_queries_intent_status",
        "medicine_assistant_queries",
        ["intent", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_medicine_assistant_queries_intent_status",
        table_name="medicine_assistant_queries",
    )
    op.drop_column("medicine_assistant_queries", "status")
    op.drop_column("medicine_assistant_queries", "intent")
