from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from app.core.time import UTC

from app.models.notification import Notification
from app.core.metrics import (
    notification_sent_total,
    notification_failed_total,
)



async def mark_notification_delivered(
    *,
    db: AsyncSession,
    notification_id: int,
    user_id: int,
):


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
    db: AsyncSession,
    notification_ids: list[int],
    user_id: int,
):

    if not notification_ids:
        return

   

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
    db: AsyncSession,
    event_id,
):

    now = datetime.now(UTC)

    await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
        )
        .values(
            push_delivered_at=now,
            delivered_at=now,
        )
    )


    notification_sent_total.inc()



async def mark_push_failed(
    *,
    db: AsyncSession,
    event_id,
    error: str,
):

    now = datetime.now(UTC)

    await db.execute(
        update(Notification)
        .where(Notification.event_id == event_id)
        .values(
            delivery_failed_at=now,
            delivery_error=error[:1000],
        )
    )


    notification_failed_total.inc()



async def mark_email_delivered(
    *,
    db: AsyncSession,
    event_id,
):

    now = datetime.now(UTC)

    await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
        )
        .values(
            email_delivered_at=now,
            delivered_at=now,
        )
    )


    notification_sent_total.inc()


async def mark_email_failed(
    *,
    db: AsyncSession,
    event_id,
    error: str,
):

    now = datetime.now(UTC)

    await db.execute(
        update(Notification)
        .where(Notification.event_id == event_id)
        .values(
            email_failed_at=now,
            email_error=error[:1000],
        )
    )

    notification_failed_total.inc()


async def mark_delivery_failed(
    *,
    db: AsyncSession,
    event_id,
    error: str,
):

    now = datetime.now(UTC)

    await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
        )
        .values(
            delivery_failed_at=now,
            delivery_error=error[:1000],
        )
    )


    notification_failed_total.inc()


async def mark_whatsapp_delivered(
    *,
    db: AsyncSession,
    event_id,
):

    now = datetime.now(UTC)

    await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
        )
        .values(
            whatsapp_delivered_at=now,
            delivered_at=now,
        )
    )

    notification_sent_total.inc()


async def mark_whatsapp_failed(
    *,
    db: AsyncSession,
    event_id,
    error: str,
):

    now = datetime.now(UTC)

    await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
        )
        .values(
            whatsapp_failed_at=now,
            whatsapp_error=error[:1000],
        )
    )

    notification_failed_total.inc()