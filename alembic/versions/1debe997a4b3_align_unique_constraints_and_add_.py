"""Match the schema to the models: unique indexes, and three missing indexes.

The last of the autogenerate noise. Two separate things, both real.

REDUNDANT INDEXES
generics.name and invitations.token_hash each carried a UNIQUE constraint AND a
plain index on the same column. A unique constraint is implemented as a unique
index, so the plain one duplicates it exactly: same column, same order, no
query can prefer it. It costs a write on every insert and update, and disk, for
nothing. The models declare a single unique index, which is the correct shape,
so the schema moves to match.

Ordering matters here and is deliberate. The new unique index is created BEFORE
the old constraint is dropped, so uniqueness is enforced by one or the other at
every moment. Dropping first would leave a window in which two concurrent
inserts could both land a duplicate — brief, but this is the constraint
protecting invitation tokens from colliding.

MISSING INDEXES
payments.appointment_id, idempotency_keys.user_id and users.google_id are
declared indexed on their models and were not indexed in the database. These
are lookups: finding a payment for an appointment, an idempotency record for a
user, a user by their Google identity. Adding them is additive and safe.

WHAT THIS BUYS
With this applied, `alembic revision --autogenerate` produces an empty
migration. That is the point of the exercise, not tidiness: a diff that is
always noisy trains whoever reviews it to skim, and the whole reason this
project's migrations were dangerous is that a genuine op.drop_table() would
have arrived in the middle of that noise and been waved through.

Revision ID: 1debe997a4b3
Revises: 0b0eec92ba4b
Create Date: 2026-08-07 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1debe997a4b3'
down_revision: Union[str, Sequence[str], None] = '0b0eec92ba4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- generics.name -----------------------------------------------------
    # Drop the plain duplicate first; generics_name_key still enforces
    # uniqueness while it is gone.
    op.drop_index("ix_generics_name", table_name="generics")
    op.create_index("ix_generics_name", "generics", ["name"], unique=True)
    op.drop_constraint("generics_name_key", "generics", type_="unique")

    # --- invitations.token_hash -------------------------------------------
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.create_index(
        "ix_invitations_token_hash", "invitations", ["token_hash"], unique=True
    )
    op.drop_constraint(
        "uq_invitations_token_hash", "invitations", type_="unique"
    )

    # --- users.google_id ---------------------------------------------------
    # No plain index existed here, so the new one is created before the
    # constraint goes.
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)
    op.drop_constraint("uq_users_google_id", "users", type_="unique")

    # --- indexes the models asked for and the schema never had -------------
    op.create_index(
        "ix_payments_appointment_id", "payments", ["appointment_id"]
    )
    op.create_index(
        "ix_idempotency_keys_user_id", "idempotency_keys", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_user_id", table_name="idempotency_keys")
    op.drop_index("ix_payments_appointment_id", table_name="payments")

    op.create_unique_constraint("uq_users_google_id", "users", ["google_id"])
    op.drop_index("ix_users_google_id", table_name="users")

    op.create_unique_constraint(
        "uq_invitations_token_hash", "invitations", ["token_hash"]
    )
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.create_index(
        "ix_invitations_token_hash", "invitations", ["token_hash"]
    )

    op.create_unique_constraint("generics_name_key", "generics", ["name"])
    op.drop_index("ix_generics_name", table_name="generics")
    op.create_index("ix_generics_name", "generics", ["name"])
