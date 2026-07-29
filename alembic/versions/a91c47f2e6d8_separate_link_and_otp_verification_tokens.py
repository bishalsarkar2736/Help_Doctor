"""separate link and OTP verification tokens

Both credentials shared one table, one hash function and one lookup:

  LINK  token_urlsafe(32)  ~256 bits, emailed as a click-through link
  OTP   6 digits            ~20 bits, typed by the user

POST /auth/verify-email resolved a token by a *global* SHA-256 lookup with no
rate limit, no attempt cap and no user scoping, so it matched OTPs too — every
brute-force defence on /auth/verify-otp (10/min throttle, 5-attempt cap, email
scoping) could be sidestepped by sending the same guesses to the link endpoint.

This migration makes the two distinguishable so each endpoint only accepts its
own credential, and widens token_hash so OTPs can be stored under a real KDF
instead of a bare SHA-256 that is reversible in under a second.

Outstanding rows are invalidated rather than guessed at: they predate the
discriminator, so there is no safe way to label them. Both kinds are
short-lived (24h / 10min) and users simply request a new one.

Revision ID: a91c47f2e6d8
Revises: f3b6d81c2a05
Create Date: 2026-07-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a91c47f2e6d8"
down_revision: Union[str, Sequence[str], None] = "f3b6d81c2a05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_verification_tokens",
        sa.Column(
            "token_type",
            sa.String(length=8),
            nullable=False,
            server_default="LINK",
        ),
    )
    op.create_index(
        "ix_email_verification_tokens_token_type",
        "email_verification_tokens",
        ["token_type"],
    )

    # Argon2 hashes are ~97 chars; SHA-256 hex is 64.
    op.alter_column(
        "email_verification_tokens",
        "token_hash",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=False,
    )

    # Unlabelled leftovers cannot be trusted as either type — retire them.
    op.execute(
        "UPDATE email_verification_tokens SET used = true WHERE used = false"
    )


def downgrade() -> None:
    # Old SHA-256 hashes fit in 64 chars; Argon2 ones do not, so anything
    # issued under the new scheme must go before narrowing the column.
    op.execute("DELETE FROM email_verification_tokens")

    op.alter_column(
        "email_verification_tokens",
        "token_hash",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.drop_index(
        "ix_email_verification_tokens_token_type",
        table_name="email_verification_tokens",
    )
    op.drop_column("email_verification_tokens", "token_type")
