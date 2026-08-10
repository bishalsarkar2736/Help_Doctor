"""Stop an outbox delete from taking notification history with it.

notifications.event_id referenced outbox_events with ON DELETE CASCADE, so
deleting an outbox event deleted every notification recorded from it.

Nothing deletes outbox events today — verified across app code, scripts, tests
and migrations; the only reference is a commented-out line in conftest, and the
dead-letter path marks an event failed and inserts a DeadLetterEvent rather than
removing the row. So no history has been lost. What made this worth changing now
is that the notification retention job establishes the pattern: the first outbox
retention job written to match it would have quietly deleted notification
history as a side effect, raising nothing and logging nothing.

WHY RESTRICT AND NOT SET NULL
SET NULL would require event_id to become nullable, and
uq_notification_event_user is (event_id, user_id). Postgres treats NULLs as
distinct, so a nullable event_id stops that constraint deduplicating
notifications at all — trading a retention risk for a correctness one, and
undoing a guarantee this project verified deliberately.

RESTRICT is compatible with the column as it stands and changes no current
behaviour, because nothing performs the delete it refuses. Its whole value is
future: a purge that would remove notifications now fails, visibly, and whoever
wrote it decides what should happen to that history instead of discovering
afterwards that it was decided for them.

The constraint is recreated under the same name, so nothing that refers to
fk_notifications_event_id needs to change.

Revision ID: 5ee7d0357fdd
Revises: 02aab6a009f0
Create Date: 2026-08-08 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5ee7d0357fdd'
down_revision: Union[str, Sequence[str], None] = '02aab6a009f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "fk_notifications_event_id"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "notifications", type_="foreignkey")

    op.create_foreign_key(
        CONSTRAINT,
        "notifications",
        "outbox_events",
        ["event_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # Back to CASCADE, and back to a delete of an outbox event silently taking
    # its notifications with it.
    op.drop_constraint(CONSTRAINT, "notifications", type_="foreignkey")

    op.create_foreign_key(
        CONSTRAINT,
        "notifications",
        "outbox_events",
        ["event_id"],
        ["id"],
        ondelete="CASCADE",
    )
