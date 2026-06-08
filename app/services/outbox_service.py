import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox_event import OutboxEvent

logger = logging.getLogger(__name__)



async def publish_event(
    *,
    db: AsyncSession,
    event_type: str,
    payload: dict,
) -> OutboxEvent:
    
    logger.warning(f"publish_event called: {event_type} | payload={payload}")
    
    event = OutboxEvent(
        event_type=event_type,
        payload=payload or {},  # ✅ safety
        correlation_id=payload.get("correlation_id"),
    )

    db.add(event)

    # ✅ ensure ID is generated immediately
    await db.flush()

    # ✅ structured logging (production useful)
    logger.info(
        "outbox_event_created",
        extra={
            "event_id": str(event.id),
            "event_type": event_type,
            "payload_keys": list(payload.keys()) if payload else [],
        },
    )

    return event