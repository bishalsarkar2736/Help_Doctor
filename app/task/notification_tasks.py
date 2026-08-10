from app.core.celery import celery_app
from app.task.base import run_async
from app.db.postgres import AsyncSessionLocal

from app.services.push_service import send_push_to_user
from app.services.notification_receipt_service import (
    mark_push_delivered,
    mark_delivery_failed,
)

import logging
import uuid

logger = logging.getLogger(__name__)


@celery_app.task(
    name="send_push_notification_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
    max_retries=5,
)

@run_async
async def send_push_notification_task(
    self,
    user_id: int,
    payload: dict,
    event_id: str,
):

    event_uuid = uuid.UUID(event_id)

    # The receipt helpers take an AsyncSession and do NOT commit internally
    # (unlike mark_notification_delivered / mark_notifications_seen), so the
    # task owns the session and the commit. Same factory the other Celery
    # tasks use — no new engine.
    async with AsyncSessionLocal() as db:

        try:

            await send_push_to_user(
                user_id=user_id,
                payload=payload,
            )

            await mark_push_delivered(
                db=db,
                event_id=event_uuid,
                user_id=user_id,
            )

            await db.commit()

        except Exception as exc:

            # Discard the failed transaction before recording the failure,
            # otherwise the session is still in a broken state.
            await db.rollback()

            try:
                await mark_delivery_failed(
                    db=db,
                    event_id=event_uuid,
                    user_id=user_id,
                    error=str(exc),
                )

                await db.commit()

            except Exception:
                # Never let bookkeeping mask the original failure below.
                await db.rollback()

                logger.exception(
                    "push_notification_mark_failed_errored",
                    extra={
                        "user_id": user_id,
                        "event_id": event_id,
                    },
                )

            logger.exception(
                "push_notification_failed",
                extra={
                    "user_id": user_id,
                    "event_id": event_id,
                    "payload": payload,
                    "error": str(exc),
                },
            )

            raise