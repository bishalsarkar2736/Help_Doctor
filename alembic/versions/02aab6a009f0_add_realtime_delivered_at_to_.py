"""Record realtime delivery in its own column.

Realtime was the one delivery channel with no timestamp of its own: it wrote
only the aggregate delivered_at, guarded on that column being NULL. So when push
or email had already delivered, a socket acknowledgement was discarded and
nothing recorded that the client received it — the aggregate could not be
explained by the per-channel columns because one channel had none.

Added because that information was being lost, not for symmetry. With it, all
four channels record their own delivery write-once and delivered_at is the
earliest of them.

Nullable with no backfill, deliberately. A NULL here means "no realtime
acknowledgement recorded", which is the truth for every existing row: whether
realtime delivered them is not recoverable, since the only evidence would have
been the aggregate, which several channels wrote. Inventing a value would be
inventing delivery history.

Existing delivered_at values are untouched.

Revision ID: 02aab6a009f0
Revises: 8dd818a365f4
Create Date: 2026-08-08 13:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '02aab6a009f0'
down_revision: Union[str, Sequence[str], None] = '8dd818a365f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("realtime_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Drops the column and with it any realtime acknowledgements recorded
    # since the upgrade. delivered_at keeps whatever it held.
    op.drop_column("notifications", "realtime_delivered_at")
