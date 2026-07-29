from datetime import (
    date,
    datetime,
    time,
)

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
    


    start_dt = datetime.combine(
        start_date,
        time.min,
    )

    end_dt = datetime.combine(
        end_date,
        time.max,
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
            Appointment.scheduled_at <= end_dt,
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
                end=(
                    appointment.scheduled_at
                    + Appointment.time_range.upper
                ),
                status=appointment.status.value
            )
        )

    return response