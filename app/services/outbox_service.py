import logging
from sqlalchemy.ext.asyncio import AsyncSession
import traceback
from app.models.outbox_event import OutboxEvent

logger = logging.getLogger(__name__)



async def publish_event(
    *,
    db: AsyncSession,
    event_type: str,
    payload: dict,
) -> OutboxEvent:
    
    print(
        "publish",
        event_type,
        "appointment_id=",
        payload.get("appointment_id"),
        "session=",
        id(db),
    )
    print("session id:", id(db))
    print("connection:", id(db.sync_session.connection()))
    
    #logger.warning(f"publish_event called: {event_type} | payload={payload}")
    
    print("\n" + "=" * 80)
    print("PUBLISH EVENT:", event_type)
    traceback.print_stack(limit=12)
    print("=" * 80 + "\n")

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