from datetime import datetime

from sqlalchemy import update

from app.core.time import UTC
from app.db.postgres import AsyncSessionLocal
from app.models.notification import Notification
from app.core.metrics import (
    notification_sent_total,
    notification_failed_total,
)

async def mark_notification_delivered(
    *,
    notification_id: int,
    user_id: int,
):

    async with AsyncSessionLocal() as db:

        await db.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.delivered_at.is_(None),
            )
            .values(
                delivered_at=datetime.now(UTC)
            )
        )

        await db.commit()


async def mark_notifications_seen(
    *,
    notification_ids: list[int],
    user_id: int,
):

    if not notification_ids:
        return

    async with AsyncSessionLocal() as db:

        await db.execute(
            update(Notification)
            .where(
                Notification.id.in_(notification_ids),
                Notification.user_id == user_id,
                Notification.seen_at.is_(None),
            )
            .values(
                seen_at=datetime.now(UTC)
            )
        )

        await db.commit()



async def mark_push_delivered(
    *,
    event_id,
):

    async with AsyncSessionLocal() as db:

        await db.execute(
            update(Notification)
            .where(
                Notification.event_id == event_id,
            )
            .values(
                push_delivered_at=datetime.now(UTC),
                delivered_at=datetime.now(UTC),
            )
        )

        await db.commit()

        notification_sent_total.inc()


async def mark_email_delivered(
    *,
    event_id,
):

    async with AsyncSessionLocal() as db:

        await db.execute(
            update(Notification)
            .where(
                Notification.event_id == event_id,
            )
            .values(
                email_delivered_at=datetime.now(UTC),
                delivered_at=datetime.now(UTC),
            )
        )

        await db.commit()

        notification_sent_total.inc()



async def mark_delivery_failed(
    *,
    event_id,
    error: str,
):

    async with AsyncSessionLocal() as db:

        await db.execute(
            update(Notification)
            .where(
                Notification.event_id == event_id,
            )
            .values(
                delivery_failed_at=datetime.now(UTC),
                delivery_error=error[:1000],
            )
        )

        await db.commit()

        notification_failed_total.inc()