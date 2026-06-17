from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notification_preference_service import (
    get_or_create_preferences,
)

from app.websocket.manager import manager


async def send_realtime_notification(
    *,
    db: AsyncSession,
    user_id: int,
    payload: dict,
) -> None:
    """
    User-facing realtime notification.

    Applies notification preferences.
    """

    prefs = await get_or_create_preferences(
        db,
        user_id,
    )

    if not prefs.realtime_enabled:
        return

    await manager.notify_user(
        user_id=user_id,
        message=payload,
    )