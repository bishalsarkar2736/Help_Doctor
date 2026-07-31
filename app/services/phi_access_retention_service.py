"""Purging expired PHI access log rows.

phi_access_logs grows on every clinical read — one row per patient record
opened — so it is the fastest-growing table in the system and the only one that
needs a retention policy of its own.

Deliberately NOT applied to audit_logs. That table records mutations (logins,
prescriptions issued, records changed), it grows far more slowly, and the
retention obligations on a change history are usually longer than on a read
trail. Purging it is a separate decision.

Design notes:

* Deletes in bounded batches. A single `DELETE ... WHERE created_at < cutoff`
  over years of rows takes a long-lived lock on a table that clinical requests
  are writing to continuously, and would stall patient-facing reads.
* Bounded batch count per run. A first run against a large backlog must not
  turn into an hours-long transaction; the remainder is picked up by the next
  nightly run.
* The cutoff scan uses ix_phi_access_logs_created_at. That index has no other
  reader — it is kept specifically for this job.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phi_access_log import PHIAccessLog

logger = logging.getLogger("app.phi_access.retention")


def _cutoff(retention_days: int) -> datetime:
    """Oldest timestamp that is still kept.

    Timezone-aware: phi_access_logs.created_at is timestamptz, and comparing it
    against a naive datetime raises rather than silently comparing wrong.
    """
    return datetime.now(timezone.utc) - timedelta(days=retention_days)


async def count_expired_phi_access_logs(
    *,
    db: AsyncSession,
    retention_days: int,
) -> int:
    """How many rows are past retention. Used for reporting and by tests."""

    return (
        await db.scalar(
            select(func.count())
            .select_from(PHIAccessLog)
            .where(PHIAccessLog.created_at < _cutoff(retention_days))
        )
        or 0
    )


async def purge_expired_phi_access_logs(
    *,
    db: AsyncSession,
    retention_days: int,
    batch_size: int,
    max_batches: int,
) -> int:
    """Delete rows older than the retention window. Returns rows deleted.

    Each batch is committed separately: the work is idempotent and order-free,
    so a failure part-way through leaves the already-deleted batches deleted
    rather than rolling back an hour of work.
    """

    cutoff = _cutoff(retention_days)
    total = 0

    for batch in range(max_batches):
        # Select the ids first, then delete by primary key. A DELETE with both
        # a LIMIT and a predicate is not expressible directly in Postgres, and
        # deleting by pk keeps each statement's lock footprint small and
        # predictable.
        ids = (
            (
                await db.execute(
                    select(PHIAccessLog.id)
                    .where(PHIAccessLog.created_at < cutoff)
                    .order_by(PHIAccessLog.id)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )

        if not ids:
            break

        await db.execute(delete(PHIAccessLog).where(PHIAccessLog.id.in_(ids)))
        await db.commit()

        total += len(ids)

        if len(ids) < batch_size:
            # Drained.
            break
    else:
        # Loop ran to max_batches without draining. Say so explicitly rather
        # than letting a permanent backlog look like a clean run.
        remaining = await count_expired_phi_access_logs(
            db=db, retention_days=retention_days
        )
        logger.warning(
            "phi_access_log_purge_incomplete",
            extra={
                "deleted": total,
                "remaining": remaining,
                "max_batches": max_batches,
                "retention_days": retention_days,
            },
        )

    logger.info(
        "phi_access_log_purge_complete",
        extra={
            "deleted": total,
            "cutoff": cutoff.isoformat(),
            "retention_days": retention_days,
        },
    )

    return total
