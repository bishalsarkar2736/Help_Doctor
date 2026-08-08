import logging

from app.config import get_settings
from app.core.celery import celery_app
from app.db.postgres import AsyncSessionLocal
from app.services.notification_retention_service import (
    purge_expired_notifications,
)
from app.task.base import run_async

logger = logging.getLogger(__name__)


async def notification_purge_job():
    settings = get_settings()

    # No outer commit: the service commits per batch on purpose, so a partial
    # run keeps the work it already did.
    async with AsyncSessionLocal() as db:
        try:
            return await purge_expired_notifications(
                db=db,
                retention_days=settings.NOTIFICATION_RETENTION_DAYS,
                batch_size=settings.NOTIFICATION_PURGE_BATCH_SIZE,
                max_batches=settings.NOTIFICATION_PURGE_MAX_BATCHES,
            )
        except Exception:
            await db.rollback()
            raise


@celery_app.task(
    name="app.tasks.notification_retention.notification_purge_task",
    bind=True,
    # The global task_time_limit is 30s, which suits the short jobs it was set
    # for and would kill this one mid-purge. Batches are committed as they go,
    # so a kill is not corrupting — but it would leave the log noise of a
    # permanently failing task. Bounded by NOTIFICATION_PURGE_MAX_BATCHES.
    time_limit=1800,
    soft_time_limit=1740,
    # No autoretry. Retention is a nightly job with no deadline: if it fails,
    # the next run selects exactly the same rows, because the criterion is age.
    # Retrying a purge that timed out because there was too much to do would
    # only repeat the timeout.
    max_retries=0,
)
@run_async
async def notification_purge_task(self):
    try:
        deleted = await notification_purge_job()
        logger.info("notification_purge_task_done", extra={"deleted": deleted})
        return deleted
    except Exception:
        logger.exception("notification_purge_task_failed")
        raise
