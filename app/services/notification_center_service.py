from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from datetime import datetime

from app.core.time import UTC


async def get_notifications(
    *,
    db: AsyncSession,
    user_id: int,
    limit: int = 50,
):
    result = await db.execute(
        select(Notification)
        .where(
            Notification.user_id == user_id
        )
        .order_by(
            Notification.created_at.desc()
        )
        .limit(limit)
    )

    return result.scalars().all()


async def get_unread_notification_count(
    *,
    db: AsyncSession,
    user_id: int,
):
    result = await db.execute(
        select(
            func.count(Notification.id)
        )
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
    )

    return result.scalar_one()


async def mark_all_notifications_read(
    *,
    db: AsyncSession,
    user_id: int,
):
    result = await db.execute(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
    )

    notifications = result.scalars().all()

    now = datetime.now(UTC)

    for notification in notifications:
        notification.read_at = now

    await db.flush()

    return len(notifications)