
from datetime import datetime, time, timedelta,date

from app.utils.clinic_time import clinic_timezone, get_clinic_day_window
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from app.schemas.appointment import AppointmentSearchOut


async def search_appointments(
    *,
    db: AsyncSession,
    clinic_id: int,
    patient: str | None = None,
    doctor: str | None = None,
    status: AppointmentStatus | None = None,
    date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AppointmentSearchOut]:

    patient_user = aliased(User)
    doctor_user = aliased(User)

    stmt = (
        select(
            Appointment,
            Patient,
            Doctor,
            patient_user,
            doctor_user,
        )
        .join(
            Patient,
            Appointment.patient_id == Patient.user_id,
        )
        .join(
            patient_user,
            Patient.user_id == patient_user.id,
        )
        .join(
            Doctor,
            Appointment.doctor_id == Doctor.id,
        )
        .join(
            doctor_user,
            Doctor.user_id == doctor_user.id,
        )
        .where(
            Appointment.clinic_id == clinic_id,
        )
    )

    #
    # Patient filter
    #

    if patient:
        pattern = f"%{patient}%"

        stmt = stmt.where(
            or_(
                patient_user.full_name.ilike(pattern),
                patient_user.email.ilike(pattern),
            )
        )

    #
    # Doctor filter
    #

    if doctor:
        pattern = f"%{doctor}%"

        stmt = stmt.where(
            or_(
                doctor_user.full_name.ilike(pattern),
                doctor_user.email.ilike(pattern),
            )
        )

    #
    # Status
    #

    if status:
        stmt = stmt.where(
            Appointment.status == status,
        )

    #
    # Exact date
    #

    # Resolved once, outside the branches: the timezone cannot change within a
    # request, and looking it up per filter would query for the same value
    # twice.
    tz_name = await clinic_timezone(db, clinic_id)

    if date:
        start, end = get_clinic_day_window(tz_name, date)

        stmt = stmt.where(
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at < end,
        )

    #
    # Date range
    #

    else:
        if start_date:
            start, _ = get_clinic_day_window(tz_name, start_date)

            stmt = stmt.where(Appointment.scheduled_at >= start)

        if end_date:
            # The END of end_date, so the range includes that whole day.
            _, end = get_clinic_day_window(tz_name, end_date)

            stmt = stmt.where(Appointment.scheduled_at < end)

    stmt = (
        stmt.order_by(
            Appointment.scheduled_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(stmt)

    rows = result.all()

    return [
        AppointmentSearchOut(
            id=appointment.id,
            scheduled_at=appointment.scheduled_at,
            status=appointment.status,

            patient_id=patient_model.user_id,
            patient_name=patient_account.full_name or "",
            patient_email=patient_account.email,

            doctor_id=doctor_model.id,
            doctor_name=doctor_account.full_name or "",
            doctor_email=doctor_account.email,

            clinic_id=appointment.clinic_id,
        )
        for (
            appointment,
            patient_model,
            doctor_model,
            patient_account,
            doctor_account,
        ) in rows
    ]