"""add user_consents

Revision ID: e4a1c62b8f37
Revises: c93f7a1b04e6

Records which legal document version each user accepted, and when. "The user
agreed to our terms" is not a defensible claim without the version they were
shown — a policy revised three times since makes an undated acceptance
worthless.

Existing users have no rows here. That is accurate rather than convenient:
they signed up before consent was collected, and back-filling a row would
manufacture evidence of an agreement that was never recorded. Collecting it
from them is a product decision (a blocking prompt on next login), not
something a migration should invent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4a1c62b8f37"
down_revision: Union[str, Sequence[str], None] = "c93f7a1b04e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            # RESTRICT, not CASCADE: deleting a user must not erase the record
            # of what they agreed to, same reasoning as phi_access_logs.
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.UniqueConstraint(
            "user_id", "document", "version", name="uq_user_consent_version"
        ),
    )

    op.create_index(
        "ix_user_consent_user_document",
        "user_consents",
        ["user_id", "document"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_consent_user_document", table_name="user_consents")
    op.drop_table("user_consents")
