from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_preference import (
    NotificationPreference,
)


async def get_or_create_preferences(
    db: AsyncSession,
    user_id: int,
) -> NotificationPreference:

    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id
        )
    )

    prefs = result.scalar_one_or_none()

    if prefs:
        return prefs

    prefs = NotificationPreference(
        user_id=user_id,
        email_enabled=True,
        # Opt-in, unlike the other three, and stated here rather than left to
        # the column default so that the intent is visible at the point where
        # every other channel's default is chosen.
        whatsapp_enabled=False,
        push_enabled=True,
        realtime_enabled=True,
    )

    db.add(prefs)

    await db.flush()

    return prefs


async def update_preferences(
    *,
    db: AsyncSession,
    user_id: int,
    email_enabled: bool | None = None,
    whatsapp_enabled: bool | None = None,
    push_enabled: bool | None = None,
    realtime_enabled: bool | None = None,
) -> NotificationPreference:

    prefs = await get_or_create_preferences(
        db,
        user_id,
    )

    if email_enabled is not None:
        prefs.email_enabled = email_enabled

    # None means "not mentioned in this PATCH", which is what keeps each channel
    # independent: turning WhatsApp on cannot disturb the other three.
    if whatsapp_enabled is not None:
        prefs.whatsapp_enabled = whatsapp_enabled

    if push_enabled is not None:
        prefs.push_enabled = push_enabled

    if realtime_enabled is not None:
        prefs.realtime_enabled = realtime_enabled

    await db.flush()

    return prefs