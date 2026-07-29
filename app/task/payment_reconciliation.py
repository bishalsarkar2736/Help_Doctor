import logging

from app.db.postgres import AsyncSessionLocal
from app.services.payment_reconciliation_service import (
    reconcile_pending_payments,
)
from app.core.celery import celery_app
from app.task.base import run_async

logger = logging.getLogger(__name__)


async def payment_reconciliation_job():

    async with AsyncSessionLocal() as db:

        try:
            await reconcile_pending_payments(
                db=db,
            )

            await db.commit()

        except Exception:
            await db.rollback()
            raise


@celery_app.task(
    name="app.tasks.payment_reconciliation.payment_reconciliation_task",
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
        logger.exception("payment_reconciliation_task_failed")
        raise