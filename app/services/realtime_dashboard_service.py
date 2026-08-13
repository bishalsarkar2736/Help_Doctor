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


def dashboard_channel(clinic_id: int) -> str:
    """The realtime dashboard channel for one clinic.

    The channel used to be the bare name "admin_dashboard", which every ADMIN
    of every clinic subscribed to on connect. publish_dashboard_update computes
    ONE clinic's overview, so each update was delivered to every other tenant's
    admins — and it is called from handle_appointment_transition_side_effects,
    which fires on every check-in, move-to-waiting, consultation start and
    completion.

    Defined here rather than spelled out at each site so the publisher and the
    subscriber cannot drift into different names, which would silently deliver
    nothing.
    """
    return f"admin_dashboard:{clinic_id}"


async def publish_dashboard_update(
    db: AsyncSession,
    clinic_id: int,
):

    overview = await get_dashboard_overview(
        db=db,
        clinic_id=clinic_id,
    )

    await manager.broadcast_channel(
        dashboard_channel(clinic_id),
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