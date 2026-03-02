from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.appointment_history import AppointmentStatusHistory


async def record_status_change(
    *,
    db: AsyncSession,
    appointment: Appointment,
    old_status,
    new_status,
    changed_by: int | None,
):
    history = AppointmentStatusHistory(
        appointment_id=appointment.id,
        old_status=old_status,
        new_status=new_status,
        changed_by=changed_by,
    )

    db.add(history)
