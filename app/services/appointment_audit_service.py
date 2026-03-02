from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment_history import AppointmentStatusHistory
from app.models.appointment import AppointmentStatus


async def log_appointment_transition(
    *,
    db: AsyncSession,
    appointment_id: int,
    from_status: AppointmentStatus,
    to_status: AppointmentStatus,
    changed_by: int | None,
):
    history = AppointmentStatusHistory(
        appointment_id=appointment_id,
        old_status=from_status,
        new_status=to_status,
        changed_by=changed_by,
    )

    db.add(history)