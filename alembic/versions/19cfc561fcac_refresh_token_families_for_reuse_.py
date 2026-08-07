"""Group refresh tokens into families, and record when one was revoked.

Refresh tokens rotate: redeeming one revokes it and issues a successor. That
limits a stolen token's life to the owner's next refresh — but nothing notices
the theft. Whoever loses that race sees a failed refresh, signs in again, and
the incident leaves no trace.

family_id links a login to every token descended from it by rotation, so when a
superseded token comes back the response can end that chain and nothing else.
Other logins by the same user are separate families: being robbed on a phone
should not sign someone out of the workstation they are treating a patient at.

revoked_at makes a replay legible. Two browser tabs waking together each hold
the same cookie and each refresh once, so the loser presents a token revoked
moments earlier. Without a timestamp that is indistinguishable from theft, and
the user gets signed out for using the product normally.

BACKFILL
Every existing token becomes its own family. They predate rotation tracking, so
their real lineage is unknown, and guessing would either merge unrelated
sessions into one family — where a single replay would revoke all of them — or
require inventing links that were never recorded. One row per family is the
honest reading and the safe one: the worst case is that a future replay revokes
less than it might have, never more.

Sessions are not disturbed. Nobody is signed out by this migration.

Revision ID: 19cfc561fcac
Revises: 1debe997a4b3
Create Date: 2026-08-07 23:35:00.000000

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '19cfc561fcac'
down_revision: Union[str, Sequence[str], None] = '1debe997a4b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    op.add_column(
        "refresh_tokens",
        sa.Column("family_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    rows = connection.execute(
        sa.text("SELECT id FROM refresh_tokens WHERE family_id IS NULL")
    ).fetchall()

    for (row_id,) in rows:
        connection.execute(
            sa.text("UPDATE refresh_tokens SET family_id = :f WHERE id = :i"),
            {"f": str(uuid.uuid4()), "i": row_id},
        )

    op.alter_column("refresh_tokens", "family_id", nullable=False)

    op.create_index(
        op.f("ix_refresh_tokens_family_id"),
        "refresh_tokens",
        ["family_id"],
    )

    # Rows revoked before this migration have no timestamp, and inventing one
    # would make an old revocation look recent — inside the race grace window,
    # where a genuine replay would be waved through as a benign retry. Left
    # NULL, which the service reads as "no longer within grace".


def downgrade() -> None:
    op.drop_index(
        op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens"
    )
    op.drop_column("refresh_tokens", "revoked_at")
    op.drop_column("refresh_tokens", "family_id")
