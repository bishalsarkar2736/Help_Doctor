from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment
from app.models.doctor_availability import DoctorAvailability
from app.models.doctor import Doctor
from app.models.clinic import Clinic
from app.core.time import UTC
from app.core.tz import to_zoneinfo
from app.try_except.exceptions import BadRequestError




async def validate_doctor_availability(
    db: AsyncSession,
    doctor_id: int,
    scheduled_at: datetime,
) -> None:
    
    # Availability is stored in the clinic's local time, so compare the booking
    # (UTC) against the doctor's clinic timezone — not raw UTC wall-clock.
    tz_name = await db.scalar(
        select(Clinic.timezone)
        .join(Doctor, Doctor.clinic_id == Clinic.id)
        .where(Doctor.id == doctor_id)
    )
    tz = to_zoneinfo(tz_name)

    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)

    local_start = scheduled_at.astimezone(tz)
    local_end = (scheduled_at + Appointment.APPOINTMENT_DURATION).astimezone(tz)

    weekday = local_start.weekday()
    start_time = local_start.time()
    end_time = local_end.time()

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