from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import UserRole
from app.models.appointment import Appointment, AppointmentStatus
from app.core.time import UTC
from app.services.appointment_transition_service import transition_appointment_locked
from app.core.constants import APPOINTMENT_DURATION_MINUTES

NO_SHOW_GRACE_MINUTES = 10


async def mark_no_show_appointments(db: AsyncSession) -> int:
    """
    Marks CONFIRMED appointments as NO_SHOW if grace window passed
    """

    now = datetime.now(UTC)
    cutoff_time = now - timedelta(
        minutes=APPOINTMENT_DURATION_MINUTES + NO_SHOW_GRACE_MINUTES
    )

    result = await db.execute(
        select(Appointment).where(
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.scheduled_at <= cutoff_time,
        )
    )

    appointments = result.scalars().all()

    for appointment in appointments:
        # await transition_appointment(
        #     db=db,
        #     appointment=appointment,
        #     new_status=AppointmentStatus.NO_SHOW,
        #     changed_by=None, 
        # )

        await transition_appointment_locked(
            db=db,
            appointment=appointment,
            new_status=AppointmentStatus.NO_SHOW,
            changed_by=None,          # or SYSTEM_USER_ID later
            actor_role=UserRole.ADMIN,   # temporary
            emit_event=True,
        )

    await db.flush()
    return len(appointments)

