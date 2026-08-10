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
from app.models.notification import (
    NotificationCategory,
)


logger = logging.getLogger(__name__)



async def create_notification(
    *,
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    category: NotificationCategory = (
        NotificationCategory.SYSTEM
    ),
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
            category=category,
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
    db: AsyncSession,
    user_id: int,
    message: str,
    appointment_id: int | None = None,
) -> None:
    
    prefs = await get_or_create_preferences(
        db,
        user_id,
    )

    if not prefs.realtime_enabled:
        return

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

# Long enough to outlast any legitimate redelivery of one event, short enough
# that the keys do not accumulate. The outbox retries at most max_retries=5
# times with min(2 ** n, 300) second backoff — under half an hour in the worst
# case — and a worker reclaiming a stale "processing" row adds to that but not
# by days.
PUSH_ENQUEUE_TTL_SECONDS = 24 * 60 * 60


def _push_enqueue_key(event_id, user_id: int) -> str:
    return f"push:enqueued:{event_id}:{user_id}"


async def _claim_push_enqueue(event_id, user_id: int) -> bool:
    """Whether THIS delivery is the one that gets to enqueue the push.

    The outbox is at-least-once, and the notification RECORD already survives
    that — create_notification uses ON CONFLICT DO NOTHING over
    uq_notification_event_user, so a redelivery finds the existing row. The
    push did not: notify_user enqueued unconditionally, so every redelivery
    sent the device another copy of a notification the user already had. The
    database looked correct while the phone buzzed three times.

    SETNX, so the claim and the test are one atomic operation and two workers
    cannot both win it.

    Keyed on (event_id, user_id), not event_id: uq_notification_event_user
    permits two users on one event, and a guard keyed on the event alone would
    silence the second recipient — trading a duplicate push for a missing one.

    FAILS OPEN. If Redis is unreachable this returns True and the push is
    enqueued. A duplicate push is a nuisance; a Redis outage silently
    suppressing every notification is an incident, and this guard exists to
    remove an annoyance, not to become a new single point of failure.
    """
    try:
        redis = await get_redis()

        claimed = await redis.set(
            _push_enqueue_key(event_id, user_id),
            "1",
            ex=PUSH_ENQUEUE_TTL_SECONDS,
            nx=True,
        )

        return bool(claimed)

    except Exception as exc:
        logger.warning(
            "push_enqueue_guard_unavailable",
            extra={
                "user_id": user_id,
                "event_id": str(event_id),
                "error": str(exc),
            },
        )

        return True


async def _release_push_enqueue(event_id, user_id: int) -> None:
    """Give the claim back when the enqueue itself failed.

    Without this, a broker that is briefly down would leave the key set, and
    the redelivery that was supposed to recover the push would see the claim
    already taken and skip it — turning a transient failure into a notification
    the user never receives.
    """
    try:
        redis = await get_redis()
        await redis.delete(_push_enqueue_key(event_id, user_id))

    except Exception as exc:
        logger.warning(
            "push_enqueue_guard_release_failed",
            extra={
                "user_id": user_id,
                "event_id": str(event_id),
                "error": str(exc),
            },
        )


async def notify_user(
    *,
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    category: NotificationCategory = (
        NotificationCategory.SYSTEM
    ),
    event_id: uuid.UUID | None = None,
    appointment_id: int | None = None,
):
    # 1️⃣ Save DB
    notification = await create_notification(
        db=db,
        user_id=user_id,
        title=title,
        message=message,
        category=category,
        event_id=event_id,
        appointment_id=appointment_id,
    )

    await delete_cache(f"notification_count:{user_id}")

    try:
        
        prefs = await get_or_create_preferences(
            db,
            user_id,
        )

        if prefs.push_enabled and await _claim_push_enqueue(
            event_id, user_id
        ):

            try:
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

            except Exception:
                # The claim is only meaningful once the task is actually
                # queued. Hand it back so a redelivery can retry, then let the
                # handler below log it as it always did.
                await _release_push_enqueue(event_id, user_id)
                raise
        
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


