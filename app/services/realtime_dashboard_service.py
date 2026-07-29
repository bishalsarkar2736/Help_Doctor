from sqlalchemy.ext.asyncio import AsyncSession

from app.websocket.manager import manager

from app.services.admin_analytics_service import (
    get_dashboard_overview,
)
from app.services.waiting_queue_service import (
    get_doctor_queue_summary,
)
import logging

logger = logging.getLogger(__name__)


async def publish_dashboard_update(
    db: AsyncSession,
    clinic_id: int,
):

    overview = await get_dashboard_overview(
        db=db,
        clinic_id=clinic_id,
    )

    await manager.broadcast_channel(
        "admin_dashboard",
        {
            "version": 1,
            "event": "dashboard_update",
            "data": overview,
        },
    )



async def publish_doctor_queue_update(
    *,
    db: AsyncSession,
    doctor_id: int,
):
    """
    Publish the live waiting queue for a single doctor.
    """

    queue = await get_doctor_queue_summary(
        db=db,
        doctor_id=doctor_id,
    )

    logger.info(
        f"Publishing doctor_queue:{doctor_id}"
    )

    await manager.broadcast_channel(
        f"doctor_queue:{doctor_id}",
        {
            "version": 1,
            "event": "doctor_queue_update",
            "data": queue.model_dump(),
        },
    )