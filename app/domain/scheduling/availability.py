from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment
from app.models.doctor_availability import DoctorAvailability
from app.try_except.exceptions import BadRequestError

APPOINTMENT_DURATION_MINUTES = 30


async def validate_doctor_availability(
    db: AsyncSession,
    doctor_id: int,
    scheduled_at: datetime,
) -> None:
    
    #appointment_end = scheduled_at + timedelta(minutes=APPOINTMENT_DURATION_MINUTES)
    appointment_end = scheduled_at + Appointment.APPOINTMENT_DURATION
    
    
    weekday = scheduled_at.weekday()
    start_time = scheduled_at.time()
    end_time = appointment_end.time()

    result = await db.execute(
        select(DoctorAvailability.id).where(
            DoctorAvailability.doctor_id == doctor_id,
            DoctorAvailability.day_of_week == weekday,
            DoctorAvailability.is_available.is_(True),
            DoctorAvailability.start_time <= start_time,
            DoctorAvailability.end_time >= end_time,
        )
    )

    availability = result.scalar_one_or_none()

    if not availability:
        raise BadRequestError("Doctor not available at this time")