from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.notification import Notification
from app.websocket.manager import manager
from datetime import datetime
from app.core.time import UTC
from app.try_except.exceptions import BadRequestError,NotFoundError
import uuid
from app.db.redis import get_redis
from app.core.cache import delete_cache
from app.task.notification_tasks import send_push_notification_task
import logging
from sqlalchemy.dialects.postgresql import insert
from app.services.notification_preference_service import (
    get_or_create_preferences,
)


logger = logging.getLogger(__name__)



async def create_notification(
    *,
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    event_id: uuid.UUID | None = None,
    appointment_id: int | None = None,
) -> Notification:

    if event_id is None:
        raise ValueError(
            "event_id is required for notification"
        )

    stmt = (
        insert(Notification)
        .values(
            user_id=user_id,
            title=title,
            message=message,
            related_appointment_id=appointment_id,
            event_id=event_id,
        )
        .on_conflict_do_nothing(
            constraint="uq_notification_event_user",
        )
        .returning(Notification.id)
    )

    result = await db.execute(stmt)

    notification_id = result.scalar_one_or_none()

    # Newly inserted
    if notification_id:

        result = await db.execute(
            select(Notification).where(
                Notification.id == notification_id
            )
        )

        return result.scalar_one()

    # Already exists
    result = await db.execute(
        select(Notification).where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
        )
    )

    return result.scalar_one()



NOTIFY_COOLDOWN_SECONDS = 5


async def notify_user_realtime(
    *,
    user_id: int,
    message: str,
    appointment_id: int | None = None,
) -> None:

    key = f"notify_cooldown:user:{user_id}"

    redis = await get_redis()

    if await redis.get(key):
        return

    await redis.set(key, "1", ex=NOTIFY_COOLDOWN_SECONDS)

    await manager.notify_user(
        user_id,
        {
            "event": "notification",   # ✅ NEW
            "message": message,
            "appointment_id": appointment_id,
        }
    )

async def notify_user(
    *,
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    event_id: uuid.UUID | None = None,
    appointment_id: int | None = None,
):
    # 1️⃣ Save DB
    notification = await create_notification(
        db=db,
        user_id=user_id,
        title=title,
        message=message,
        event_id=event_id,
        appointment_id=appointment_id,
    )

    await delete_cache(f"notification_count:{user_id}")

    try:
        
        # send_push_notification_task.delay(
        #     user_id,
        #     {
        #         "title": title,
        #         "body": message,
        #         "event": "notification",
        #         "appointment_id": appointment_id,
        #     }
        # )
        prefs = await get_or_create_preferences(
            db,
            user_id,
        )

        if prefs.push_enabled:

            send_push_notification_task.delay(
                user_id = user_id,
                payload = {
                    "title": title,
                    "body": message,
                    "event": "notification",
                    "appointment_id": appointment_id,
                },
                event_id=str(event_id),
            )
        
    except Exception as e:
        logger.error(
            "Failed to enqueue push notification",
            extra={
                "user_id": user_id,
                "error": str(e),
            },
        )

    return notification


async def mark_notification_as_read(
    db,
    user,
    notification_id: int,
) ->Notification:
    
    # 1️⃣ Fetch notification
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise NotFoundError("Notification not found")

    # 2️⃣ Ownership check (CRITICAL RULE)
    if notification.user_id != user.id:
        raise BadRequestError("Not authorized to read this notification")

    # 3️⃣ Mark as read only if not already read
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(notification)

        # invalidate unread count cache
        await delete_cache(f"notification_count:{user.id}")

    return notification


async def sync_notifications(
    *,
    db: AsyncSession,
    user_id: int,
    after_id: int | None = None,
    limit: int = 50,
):
    query = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.id.asc())
        .limit(limit)
    )

    if after_id is not None:
        query = query.where(
            Notification.id > after_id
        )

    result = await db.execute(query)

    return result.scalars().all()


