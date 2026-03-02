import asyncio
from sqlalchemy import select
from datetime import datetime

from app.db.session import async_sessionmaker
from app.models.outbox_event import OutboxEvent
from app.models.notification import Notification
from app.websocket.manager import manager
from app.core.time import UTC


async def process_events():
    while True:
        async with async_sessionmaker() as db:
            result = await db.execute(
                select(OutboxEvent)
                .where(OutboxEvent.is_processed.is_(False))
                .order_by(OutboxEvent.created_at)
                .limit(20)
                .with_for_update(skip_locked=True)
            )

            events = result.scalars().all()

            for event in events:
                try:
                    await handle_event(db, event)

                    event.is_processed = True
                    event.processed_at = datetime.now(UTC)

                except Exception:
                    event.retry_count += 1

            await db.commit()

        await asyncio.sleep(2)


async def handle_event(db, event: OutboxEvent):

    if event.event_type == "APPOINTMENT_STATUS_CHANGED":

        appointment_id = event.payload["appointment_id"]
        new_status = event.payload["new_status"]
        patient_id = event.payload["patient_id"]

        # 1️⃣ Persist notification
        notification = Notification(
            user_id=patient_id,
            title="Appointment Update",
            message=f"Your appointment status changed to {new_status}",
            related_appointment_id=appointment_id,
        )

        db.add(notification)

        # 2️⃣ Real-time websocket push
        await manager.notify_user(
            patient_id,
            f"Your appointment status changed to {new_status}"
        )


if __name__ == "__main__":
    asyncio.run(process_events())