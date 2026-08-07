"""Store refresh tokens as SHA-256 digests instead of plaintext.

A refresh token is a credential: presenting it returns a working access token
for its owner. Kept in the clear, anything that could read this table held live
sessions for every signed-in user, renewable indefinitely. Password reset
tokens, email verification tokens and invitations were already hashed; refresh
tokens were the one member of that family still stored as-is, and the
longest-lived of the four.

EXISTING SESSIONS SURVIVE.
The digest is deterministic, so the current plaintext values are hashed in
place rather than discarded. Nobody is logged out by this migration. Forcing a
re-login would also have been defensible, but it is an avoidable disruption for
a change that does not require it.

Backfilled in Python rather than SQL: hashing in the database would need the
pgcrypto extension, which is one more thing to be installed on the target, and
the digest has to match app.security.tokens.hash_token exactly or every session
breaks. Using that function itself is the only way to be sure.

Revision ID: 5fc78c7f911c
Revises: e2f6b8c4a713
Create Date: 2026-08-07 22:51:13.492042

"""
import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5fc78c7f911c'
down_revision: Union[str, Sequence[str], None] = 'e2f6b8c4a713'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _digest(token: str) -> str:
    # Inlined rather than imported from app.security.tokens: a migration has to
    # keep working if that helper is later moved or changed, because it
    # describes what the database did on the day it ran.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def upgrade() -> None:
    connection = op.get_bind()

    # Nullable first, so the backfill has somewhere to write.
    op.add_column(
        "refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=True),
    )

    rows = connection.execute(
        sa.text("SELECT id, token FROM refresh_tokens WHERE token IS NOT NULL")
    ).fetchall()

    for row_id, token in rows:
        connection.execute(
            sa.text(
                "UPDATE refresh_tokens SET token_hash = :h WHERE id = :i"
            ),
            {"h": _digest(token), "i": row_id},
        )

    # Any row that could not be backfilled has no usable credential in it. It
    # cannot be matched by a lookup, so deleting it loses nothing and keeps the
    # NOT NULL below from failing on junk.
    connection.execute(
        sa.text("DELETE FROM refresh_tokens WHERE token_hash IS NULL")
    )

    op.alter_column("refresh_tokens", "token_hash", nullable=False)

    op.create_index(
        op.f("ix_refresh_tokens_token_hash"),
        "refresh_tokens",
        ["token_hash"],
        unique=True,
    )

    # Dropped last, and only once every row has a digest. The plaintext is the
    # thing this migration exists to remove.
    op.drop_index("ix_refresh_tokens_token", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "token")


def downgrade() -> None:
    """Restores the column, NOT the tokens.

    A digest cannot be reversed, so the plaintext is gone for good. Every row
    is deleted rather than resurrected with an empty token, which would create
    rows that match nothing and look like valid sessions. Downgrading logs
    everyone out; there is no version of this that does not.
    """
    op.execute("DELETE FROM refresh_tokens")

    op.add_column(
        "refresh_tokens",
        sa.Column("token", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_refresh_tokens_token", "refresh_tokens", ["token"], unique=True
    )

    op.drop_index(
        op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens"
    )
    op.drop_column("refresh_tokens", "token_hash")
