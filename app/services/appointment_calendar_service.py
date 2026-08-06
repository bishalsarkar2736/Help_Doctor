from datetime import date

from app.utils.clinic_time import clinic_timezone, get_clinic_day_window

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import (
    selectinload,
)

from app.models.appointment import (
    Appointment,
)

from app.models.doctor import (
    Doctor,
)

from app.schemas.appointment_calendar_schema import (
    CalendarAppointmentResponse,
)





async def get_calendar_appointments(
    *,
    db: AsyncSession,
    clinic_id : int,
    start_date: date,
    end_date: date,
    doctor_id: int | None = None,
):
    


    # These were NAIVE datetimes compared against a timestamptz column, so the
    # database read them as UTC while the appointments they filtered were made
    # in clinic-local time. The end was also time.max, which drops the final
    # second of the range; the window is now half-open on local midnights.
    tz_name = await clinic_timezone(db, clinic_id)

    start_dt, end_dt = get_clinic_day_window(
        tz_name,
        start_date,
        days=(end_date - start_date).days + 1,
    )

    stmt = (
        select(Appointment)
        .options(
            selectinload(
                Appointment.doctor
            ).selectinload(
                Doctor.user
            )
        )
        .where(
            Appointment.scheduled_at >= start_dt,
            Appointment.scheduled_at < end_dt,
            Appointment.clinic_id == clinic_id,
        )
        .order_by(
            Appointment.scheduled_at.asc()
        )
    )

    if doctor_id is not None:

        stmt = stmt.where(
            Appointment.doctor_id
            == doctor_id
        )

    result = await db.execute(stmt)

    appointments = (
        result.scalars()
        .unique()
        .all()
    )

    response = []

    for appointment in appointments:

        doctor_name = (
            appointment.doctor.user.full_name
            if (
                appointment.doctor
                and appointment.doctor.user
            )
            else f"Doctor #{appointment.doctor_id}"
        )

        patient_title = (
            f"Patient #{appointment.patient_id}"
        )

        response.append(
            CalendarAppointmentResponse(
                id=appointment.id,
                title=patient_title,
                doctor_id=appointment.doctor_id,
                doctor_name=doctor_name,
                start=appointment.scheduled_at,
                # appointment.time_range, not Appointment.time_range. The class
                # attribute is a SQLAlchemy column expression, and adding one to
                # a datetime raises — so this endpoint crashed on any non-empty
                # calendar and only ever "worked" when there was nothing to
                # show. The row's own range is what has an end.
                end=appointment.time_range.upper,
                status=appointment.status.value
            )
        )

    return response