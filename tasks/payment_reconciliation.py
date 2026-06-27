import logging

from app.core.celery import celery_app
from app.task.base import run_async
from app.task.payment_reconciliation import (
    payment_reconciliation_job,
)

logger = logging.getLogger(__name__)


@celery_app.task(
    name="payment_reconciliation_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
@run_async
async def payment_reconciliation_task(self):

    try:

        await payment_reconciliation_job()

    except Exception:

        logger.exception(
            "payment_reconciliation_task_failed"
        )

        raise