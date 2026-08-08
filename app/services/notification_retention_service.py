"""Purging expired notification rows.

notifications grows by one row per recipient per event and nothing ever removed
any of them. Unlike phi_access_logs, which is a compliance trail, this table
holds "the user was told" — the clinical facts themselves live in appointments,
prescriptions and payments and are kept under their own rules. Deleting a
notification destroys a message, not a record.

Nothing reads rows this old: the list endpoint pages newest-first, the unread
count only looks at read_at IS NULL, and /sync walks forward from an id the
client already has.

WHAT IS DELETED
Rows older than the retention window, and nothing else. Age is the only
criterion, which makes a run deterministic — the same cutoff selects the same
rows however many times it executes — and means nothing recent is ever at risk
regardless of read state.

A CONSEQUENCE WORTH STATING
That includes rows that are old AND still unread. Sparing those would leave the
table unbounded exactly where it grows worst: an abandoned account accumulates
unread notifications forever and never reads them, so "unread" would become a
permanent exemption rather than a temporary one. If unread rows should instead
be kept indefinitely, that is a policy decision to take deliberately, not a
default to arrive at by accident.

Design notes, following phi_access_retention_service:

* Bounded batches, committed one at a time. A single DELETE over years of rows
  holds a long lock on a table that delivery is writing to continuously.
* Bounded batch count per run, so a first run against a backlog cannot become
  an hours-long transaction; the remainder is picked up by the next run.
* The scan is ordered by primary key, not by created_at, and needs no index of
  its own. id is serial and created_at defaults to now() at insert, so the two
  increase together: the expired rows are the lowest ids, a pk-ordered scan
  meets them immediately and stops at the batch limit. Adding a created_at
  index for this job alone would cost a write on every notification to save a
  nightly scan that is already cheap.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification

logger = logging.getLogger("app.notifications.retention")


def _cutoff(retention_days: int) -> datetime:
    """Oldest timestamp that is still kept.

    Timezone-aware: notifications.created_at is timestamptz, and comparing it
    against a naive datetime raises rather than silently comparing wrong.
    """
    return datetime.now(timezone.utc) - timedelta(days=retention_days)


async def count_expired_notifications(
    *,
    db: AsyncSession,
    retention_days: int,
) -> int:
    """How many rows are past retention. Used for reporting and by tests."""

    return (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.created_at < _cutoff(retention_days))
        )
        or 0
    )


async def purge_expired_notifications(
    *,
    db: AsyncSession,
    retention_days: int,
    batch_size: int,
    max_batches: int,
) -> int:
    """Delete notifications older than the retention window. Returns the count.

    Each batch is committed separately: the work is idempotent and order-free,
    so a failure part-way through keeps the batches already deleted instead of
    rolling back the whole run.
    """

    cutoff = _cutoff(retention_days)
    total = 0

    for _ in range(max_batches):
        # Ids first, then delete by primary key. Postgres cannot express a
        # DELETE with both a predicate and a LIMIT, and deleting by pk keeps
        # each statement's lock footprint small and predictable.
        ids = (
            (
                await db.execute(
                    select(Notification.id)
                    .where(Notification.created_at < cutoff)
                    .order_by(Notification.id)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )

        if not ids:
            break

        await db.execute(delete(Notification).where(Notification.id.in_(ids)))
        await db.commit()

        total += len(ids)

        if len(ids) < batch_size:
            # Drained.
            break
    else:
        # Ran to max_batches without draining. Said explicitly, so a permanent
        # backlog does not read as a clean run.
        remaining = await count_expired_notifications(
            db=db, retention_days=retention_days
        )
        logger.warning(
            "notification_purge_incomplete",
            extra={
                "deleted": total,
                "remaining": remaining,
                "max_batches": max_batches,
                "retention_days": retention_days,
            },
        )

    logger.info(
        "notification_purge_complete",
        extra={
            "deleted": total,
            "cutoff": cutoff.isoformat(),
            "retention_days": retention_days,
        },
    )

    return total
