"""Make a signed doctor-signature URL revocable.

Doctor signatures are served through short-lived HMAC-signed URLs rather than
being publicly readable at media/signatures/doctor_<id>.png. Signing is
stateless — nothing about a minted URL is stored — which is what avoids a table
per URL and a data migration of the existing keys, but it also means a URL
cannot be withdrawn: whoever holds one can read the signature until it expires.

This column is the revocation handle. The version is folded into the signed URL
and into the MAC, and the serving route refuses any URL whose version is not the
doctor's current one. Uploading a signature bumps it, so replacing a signature
invalidates every link to the previous one immediately instead of an expiry
window later.

WHY A COUNTER AND NOT A STORED TOKEN TABLE
One integer per doctor, versus a row per issued URL that has to be written on
every profile load and swept afterwards. The counter gives immediate revocation
at the granularity that actually matters — "every URL for this doctor's
signature, now" — which is the only granularity a signature replacement needs.
Per-URL revocation would buy nothing here and would put a write on a read path.

BACKFILL AND WHY THE SERVER DEFAULT MATTERS
Existing rows must land on 1, matching the model default, so that URLs minted
after this migration verify against a real number. NULL would compare unequal to
every version and lock every current doctor out of their own signature; the
column is therefore NOT NULL with server_default="1", which fills existing rows
in the same statement.

The server default is kept rather than dropped afterwards: rows are also created
by fixtures and by any INSERT that does not mention the column, and a database
default is what keeps those consistent with the model's default=1.

No signature is invalidated by this migration itself. Every doctor starts at
version 1, and URLs are minted at whatever the column currently holds, so the
only thing that revokes anything is a subsequent upload.

Revision ID: c7a4e1f92b83
Revises: 5ee7d0357fdd
Create Date: 2026-08-17 09:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7a4e1f92b83'
down_revision: Union[str, Sequence[str], None] = '5ee7d0357fdd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "doctors",
        sa.Column(
            "signature_access_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    # Dropping this re-opens nothing on its own: signature URLs stay signed and
    # expiring. It only removes the ability to revoke one early, so any URL
    # outstanding at the time remains readable until its expiry — at most
    # SIGNED_FILE_URL_TTL_SECONDS.
    op.drop_column("doctors", "signature_access_version")
