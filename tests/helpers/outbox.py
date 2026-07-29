from app.models.outbox_event import OutboxEvent


async def create_outbox_event(
    db,
    event,
) -> OutboxEvent:
    outbox = OutboxEvent(
        event_type=event.event_type,
        payload=event.model_dump(),
    )

    db.add(outbox)

    await db.flush()
    await db.refresh(outbox)

    return outbox