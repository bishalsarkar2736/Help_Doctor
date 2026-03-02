from app.models.outbox_event import OutboxEvent


async def publish_event(
    *,
    db,
    event_type: str,
    payload: dict,
):
    event = OutboxEvent(
        event_type=event_type,
        payload=payload,
    )

    db.add(event)