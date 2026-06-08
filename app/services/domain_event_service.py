from sqlalchemy.ext.asyncio import AsyncSession

from app.services.outbox_service import (
    publish_event,
)

from app.schemas.event import (
    BaseEvent,
)

from app.core.correlation import (
    correlation_id_ctx,
)

async def publish_domain_event(
    *,
    db: AsyncSession,
    event: BaseEvent,
):
    
    payload = event.model_dump()
    
    payload["correlation_id"] = (
        payload.get("correlation_id")
        or correlation_id_ctx.get()
    )

    await publish_event(
        db=db,
        event_type=event.event_type,
        payload=payload,
    )