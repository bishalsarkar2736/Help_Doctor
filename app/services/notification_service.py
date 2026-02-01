from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.websocket.manager import manager


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
    await db.commit()
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
