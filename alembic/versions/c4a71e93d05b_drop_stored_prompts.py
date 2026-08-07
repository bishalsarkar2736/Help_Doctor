"""stop storing what patients typed into the medicine assistant

Revision ID: c4a71e93d05b
Revises: d5b83f1a7c40

A chat box invites people to describe their health, and the medicine assistant
was keeping every word of it. The stored rows include "can i take something in
place of this" — a patient's own question, in plain text, in a table with no
retention policy, surfaced to clinic admins through three analytics reports.

The surest way never to mishandle that text is never to keep it. The columns go
rather than being nulled: a nullable column is one an accidental writer can
fill again, and the policy is better enforced by the schema than by everyone
remembering.

WHAT SURVIVES
-------------
Everything the analytics actually need. medicine_name, medicine_id, timestamps,
token counts and latency all stay, so "which medicines are asked about", "how
often do we fail to match", "what does this cost" keep working — keyed on the
medicine rather than on the patient's words.

medicine_ai_logs.answer goes with it. It is the assistant's own output rather
than the patient's, but it is generated text that can quote the question back,
and it is not on the list of what this system stores. What it said remains
reconstructible from medicine_id plus intent, since every answer is formatted
from a JSON payload the backend produced.

IRREVERSIBLE
------------
Eight rows in medicine_assistant_queries hold question text and lose it here.
medicine_ai_logs is empty — the AI has never been enabled — so nothing is lost
there. The downgrade re-creates the columns but cannot bring the text back, and
should not: recovering it is not a goal.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4a71e93d05b"
down_revision: Union[str, Sequence[str], None] = "d5b83f1a7c40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("medicine_assistant_queries", "question")

    op.drop_column("medicine_ai_logs", "question")
    op.drop_column("medicine_ai_logs", "answer")


def downgrade() -> None:
    # Nullable on the way back, because the text is gone and existing rows have
    # nothing to put in a NOT NULL column.
    op.add_column(
        "medicine_ai_logs",
        sa.Column("answer", sa.Text(), nullable=True),
    )
    op.add_column(
        "medicine_ai_logs",
        sa.Column("question", sa.Text(), nullable=True),
    )
    op.add_column(
        "medicine_assistant_queries",
        sa.Column("question", sa.String(length=1000), nullable=True),
    )
