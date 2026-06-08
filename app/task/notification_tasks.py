from app.core.celery import celery_app
from app.services.push_service import send_push_to_user
import logging
import asyncio
import uuid

from app.services.notification_receipt_service import (
    mark_push_delivered,
    mark_delivery_failed,
)


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


def send_push_notification_task(
    self, 
    user_id: int,
    payload: dict,
    event_id: str,
):
    
    event_uuid = uuid.UUID(event_id)
    
    async def _run():

        await send_push_to_user(
            user_id=user_id,
            payload=payload,
        )

        await mark_push_delivered(
            event_id=event_uuid,
        )

    try:
        asyncio.run(_run())

    except Exception as exc:

        

        asyncio.run(
            mark_delivery_failed(
                event_id=event_uuid,
                error=str(exc),
            )
        )

        logger.error(
            "Push notification failed",
            extra={
                "user_id": user_id,
                "event_id": event_id,
                "payload": payload,
                "error": str(exc),
            },
        )
        raise