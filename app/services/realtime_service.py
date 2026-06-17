import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User, UserRole
from app.websocket.manager import manager
from app.services.realtime_sync_service import (
    send_realtime_sync,
)


async def notify_admins(
    db: AsyncSession,
    payload: dict,
):
    """
    Send real-time event to all admins (optimized)
    """

    # ✅ Fetch ONLY IDs (lightweight query)
    result = await db.execute(
        select(User.id).where(User.role == UserRole.ADMIN)
    )

    admin_ids = result.scalars().all()

    if not admin_ids:
        return

    # ✅ Send in parallel (faster)
    # await asyncio.gather(
    #     *[
    #         manager.notify_user(admin_id, payload)
    #         for admin_id in admin_ids
    #     ],
    #     return_exceptions=True  # ❗ never break main flow
    # )

    await asyncio.gather(
        *[
            send_realtime_sync(
                user_id=admin_id,
                payload=payload,
            )
            for admin_id in admin_ids
        ],
        return_exceptions=True,
    )