"""widen users.mfa_secret for encryption at rest

Revision ID: c93f7a1b04e6
Revises: b7c4a91e5d38

users.mfa_secret is now encrypted by app/security/field_encryption.py. A Fernet
token wrapping a 32-character TOTP seed is roughly 140 characters, so the old
VARCHAR(64) would silently TRUNCATE the ciphertext on write and destroy the
secret — the user would keep a working authenticator app and be permanently
unable to log in.

Data migration is deliberately NOT performed here.

Encryption keys live in application config, and reaching into app crypto from a
migration couples this file to code that will keep changing; a year from now
`alembic upgrade head` on a fresh database should not depend on today's key
derivation still existing. Instead EncryptedSecret reads pre-existing plaintext
transparently (it recognises ciphertext by Fernet's "gAAAAA" prefix) and
re-encrypts on the next write.

This deployment has zero rows with a secret set, so nothing is left in
plaintext here. On a deployment that does have them, either let them convert
naturally as users touch their MFA settings, or force it with a one-off
re-save.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c93f7a1b04e6"
down_revision: Union[str, Sequence[str], None] = "b7c4a91e5d38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "mfa_secret",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Narrowing back would truncate any encrypted value that is already
    # stored, which destroys the secret rather than reverting it. Clear the
    # column instead: affected users re-enrol, which is recoverable. Silent
    # data corruption is not.
    op.execute("UPDATE users SET mfa_secret = NULL, mfa_enabled = false")

    op.alter_column(
        "users",
        "mfa_secret",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
