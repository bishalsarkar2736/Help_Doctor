from sqlalchemy.ext.asyncio import AsyncSession

from app.websocket.manager import manager

from app.services.admin_analytics_service import (
    get_dashboard_overview,
)


async def publish_dashboard_update(
    db: AsyncSession,
):

    overview = await get_dashboard_overview(
        db
    )

    await manager.broadcast_channel(
        "admin_dashboard",
        {
            "version": 1,
            "event": "dashboard_update",
            "data": overview,
        },
    )