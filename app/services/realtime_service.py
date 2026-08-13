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
    *,
    clinic_id: int,
):
    """Send a real-time event to the admins of ONE clinic.

    `clinic_id` is keyword-only and required on purpose. This previously
    selected every ADMIN row in the database and pushed the payload to all of
    them, so an event about one clinic reached every other tenant's admin
    panel. A default here — or a positional argument that is easy to forget —
    would let the next caller reintroduce that silently; being unable to call
    this function without naming a clinic is the point.
    """

    # ✅ Fetch ONLY IDs (lightweight query)
    result = await db.execute(
        select(User.id).where(
            User.role == UserRole.ADMIN,
            User.clinic_id == clinic_id,
        )
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