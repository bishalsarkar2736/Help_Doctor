from datetime import timedelta,datetime
from app.core.time import UTC
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment, AppointmentStatus
from sqlalchemy import select



async def mark_no_show_appointments(db: AsyncSession):
    now = datetime.now(UTC)

    result = await db.execute(
        select(Appointment).where(
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.scheduled_at + timedelta(minutes=45) < now,
        )
    )

    for appointment in result.scalars():
        appointment.status = AppointmentStatus.NO_SHOW

    await db.flush()

