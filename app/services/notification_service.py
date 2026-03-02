from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.notification import Notification
from app.websocket.manager import manager
from datetime import datetime
from app.core.time import UTC
from app.try_except.exceptions import BadRequestError,ForbiddenError

async def create_notification(
    *,
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    appointment_id: int | None = None,
):
    """
    Persist notification to DB (audit trail)
    """
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        related_appointment_id=appointment_id,
    )
    db.add(notification)
    await db.flush()
    await db.refresh(notification)
    return notification


async def notify_user(
    *,
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    appointment_id: int | None = None,
):
    """
    Unified notification:
    1. Save notification to DB
    2. Push real-time WebSocket message
    """

    # 1️⃣ Persist notification
    await create_notification(
        db=db,
        user_id=user_id,
        title=title,
        message=message,
        appointment_id=appointment_id,
    )

    # 2️⃣ Real-time WebSocket
    await manager.notify_user(user_id, message)




async def mark_notification_as_read(
    db,
    user,
    notification_id: int,
):
    # 1️⃣ Fetch notification
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise ForbiddenError("Notification not found")

    # 2️⃣ Ownership check (CRITICAL RULE)
    if notification.user_id != user.id:
        raise BadRequestError("Not authorized to read this notification")

    # 3️⃣ Mark as read only if not already read
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(notification)

    return notification


