"""Index notifications on (user_id, created_at).

notifications.user_id had a foreign key but no index — Postgres does not create
one for an FK — and the only index containing it, uq_notification_event_user,
leads with event_id and so cannot serve `WHERE user_id = ?`. Listing a user's
notifications, counting their unread and /sync were therefore sequential scans
of the entire table, on a table nothing ever pruned.

Composite because the list query is

    WHERE user_id = ? [AND read_at IS [NOT] NULL] [AND category = ?]
    ORDER BY created_at DESC
    LIMIT ? OFFSET ?

so leading on user_id and continuing on created_at satisfies the filter and the
ordering from a single index scan with no sort step.

Ascending, deliberately. A btree is scanned backwards at the same cost, so
ORDER BY created_at DESC is served as-is; declaring DESC would make this an
expression index, which alembic compares unreliably and which buys nothing.

LOCKING
A plain CREATE INDEX takes a SHARE lock, blocking writes to notifications while
it builds. The table is small today, and a plain create is atomic and rolls back
cleanly if it fails. If it is large by the time this runs, the alternative is
CREATE INDEX CONCURRENTLY inside `op.get_context().autocommit_block()`, which
does not block writers but cannot run in a transaction and leaves an INVALID
index behind if it fails. Chosen deliberately for the smaller, reversible option
rather than invisibly.

Revision ID: 8dd818a365f4
Revises: 0562f48dd3b6
Create Date: 2026-08-08 12:55:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8dd818a365f4'
down_revision: Union[str, Sequence[str], None] = '0562f48dd3b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_notifications_user_id_created_at",
        "notifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_user_id_created_at",
        table_name="notifications",
    )
