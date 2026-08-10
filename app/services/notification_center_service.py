from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import ( 
    Notification,NotificationCategory
)
from datetime import datetime

from app.core.time import UTC
from app.core.cache import delete_cache
from app.try_except.exceptions import (
    NotFoundError,
    ForbiddenError,
)


async def get_notifications(
    *,
    db: AsyncSession,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    is_read: bool | None = None,
    category: NotificationCategory | None = None,
):
    
    stmt = (
        select(Notification)
        .where(
            Notification.user_id == user_id
        )
    )

    if is_read is True:
        stmt = stmt.where(
            Notification.read_at.is_not(None)
        )

    if is_read is False:
        stmt = stmt.where(
            Notification.read_at.is_(None)
        )
    
    if category is not None:
        stmt = stmt.where(
            Notification.category == category
        )

    stmt = (
        stmt.order_by(
            Notification.created_at.desc()
        )
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(stmt)

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

        # Reading implies having seen it. Only filled when empty: a seen_at
        # already recorded by the client is when the user actually saw it, and
        # is earlier and more accurate than this.
        #
        # The invariant is one-directional — read implies seen, seen does not
        # imply read — because a notification can appear on screen without
        # being opened.
        if notification.seen_at is None:
            notification.seen_at = now

    await db.flush()

    # The same key mark_notification_read invalidates. Without this the unread
    # badge kept serving its cached value for up to the TTL after the user had
    # just cleared everything.
    await delete_cache(f"notification_count:{user_id}")

    return len(notifications)


async def mark_notification_read(
    *,
    db: AsyncSession,
    user_id: int,
    notification_id: int,
):
    notification = await db.get(
        Notification,
        notification_id,
    )

    if not notification:
        raise NotFoundError(
            "Notification not found"
        )

    if notification.user_id != user_id:
        raise ForbiddenError(
            "Not allowed"
        )

    if notification.read_at is None:
        now = datetime.now(UTC)

        notification.read_at = now

        # Reading implies having seen it; an existing seen_at is left alone.
        if notification.seen_at is None:
            notification.seen_at = now

        await db.flush()

        await delete_cache(
            f"notification_count:{user_id}"
        )

    return notification