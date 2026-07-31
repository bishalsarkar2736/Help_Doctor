import logging

from app.config import get_settings
from app.core.celery import celery_app
from app.db.postgres import AsyncSessionLocal
from app.services.phi_access_retention_service import (
    purge_expired_phi_access_logs,
)
from app.task.base import run_async

logger = logging.getLogger(__name__)


async def phi_access_log_purge_job():
    settings = get_settings()

    # No outer commit: the service commits per batch on purpose, so a partial
    # run keeps the work it already did.
    async with AsyncSessionLocal() as db:
        try:
            return await purge_expired_phi_access_logs(
                db=db,
                retention_days=settings.PHI_ACCESS_LOG_RETENTION_DAYS,
                batch_size=settings.PHI_ACCESS_LOG_PURGE_BATCH_SIZE,
                max_batches=settings.PHI_ACCESS_LOG_PURGE_MAX_BATCHES,
            )
        except Exception:
            await db.rollback()
            raise


@celery_app.task(
    name="app.tasks.phi_access_retention.phi_access_log_purge_task",
    bind=True,
    # The global task_time_limit is 30s, which suits the short jobs it was set
    # for and would kill this one mid-purge. Batches are committed as they go,
    # so a kill is not corrupting — but it would leave the log noise of a
    # permanently failing task. Bounded by PHI_ACCESS_LOG_PURGE_MAX_BATCHES.
    time_limit=1800,
    soft_time_limit=1740,
    # No autoretry. Retention is a nightly job with no deadline: if it fails,
    # the next run picks up exactly the same backlog. Retrying a purge that
    # timed out because there was too much to do would just repeat the timeout.
    max_retries=0,
)
@run_async
async def phi_access_log_purge_task(self):
    try:
        deleted = await phi_access_log_purge_job()
        logger.info("phi_access_log_purge_task_done", extra={"deleted": deleted})
        return deleted
    except Exception:
        logger.exception("phi_access_log_purge_task_failed")
        raise
