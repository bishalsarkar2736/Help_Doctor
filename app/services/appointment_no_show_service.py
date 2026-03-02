from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.appointment import Appointment, AppointmentStatus
from app.core.time import UTC
from app.domain.fsm.appointment_transition import transition_appointment


APPOINTMENT_DURATION_MINUTES = 30
NO_SHOW_GRACE_MINUTES = 15


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
        await transition_appointment(
            db=db,
            appointment=appointment,
            new_status=AppointmentStatus.NO_SHOW,
            changed_by=None, 
        )

    await db.flush()
    return len(appointments)

