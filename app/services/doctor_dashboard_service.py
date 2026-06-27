from datetime import datetime
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import UTC

from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)

from app.schemas.doctor_dashboard_schema import (
    DoctorDashboardAppointment,
    DoctorDashboardResponse,
    DoctorDashboardRecentPatient,
)

from app.services.doctor_revenue_service import (
    get_doctor_revenue_today,
    get_doctor_revenue_this_month,
)

from app.services.doctor_analytics_service import get_completion_rate



async def get_doctor_dashboard(
    *,
    db: AsyncSession,
    doctor_id: int,
    clinic_id : int,
) -> DoctorDashboardResponse:
    

    now = datetime.now(UTC)

    start_of_day = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    end_of_day = start_of_day + timedelta(
        days=1
    )

    # ---------------------------------
    # TODAY APPOINTMENTS
    # ---------------------------------

    result = await db.execute(
        select(
            func.count(Appointment.id)
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.clinic_id == clinic_id,
            Appointment.scheduled_at >= start_of_day,
            Appointment.scheduled_at < end_of_day,
        )
    )

    today_appointments = result.scalar_one()

    # ---------------------------------
    # UPCOMING APPOINTMENTS
    # ---------------------------------

    result = await db.execute(
        select(
            func.count(Appointment.id)
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.clinic_id == clinic_id,
            Appointment.scheduled_at > now,
            Appointment.status.in_(
                [
                    AppointmentStatus.PENDING,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.SCHEDULED,
                ]
            ),
        )
    )

    upcoming_appointments = (
        result.scalar_one()
    )

    # ---------------------------------
    # PENDING APPOINTMENTS
    # ---------------------------------

    result = await db.execute(
        select(
            func.count(Appointment.id)
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.clinic_id == clinic_id,
            Appointment.status
            == AppointmentStatus.PENDING,
        )
    )

    pending_appointments = (
        result.scalar_one()
    )

    # ---------------------------------
    # COMPLETED TODAY
    # ---------------------------------

    result = await db.execute(
        select(
            func.count(Appointment.id)
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.clinic_id == clinic_id,
            Appointment.status
            == AppointmentStatus.COMPLETED,
            Appointment.completed_at >= start_of_day,
            Appointment.completed_at < end_of_day,
        )
    )

    completed_today = (
        result.scalar_one()
    )

    # ---------------------------------
    # CANCELLED TODAY
    # ---------------------------------

    result = await db.execute(
        select(
            func.count(Appointment.id)
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.clinic_id == clinic_id,
            Appointment.status
            == AppointmentStatus.CANCELLED,
            Appointment.cancelled_at >= start_of_day,
            Appointment.cancelled_at < end_of_day,
        )
    )

    cancelled_today = (
        result.scalar_one()
    )

    # ---------------------------------
    # RECENT APPOINTMENTS
    # ---------------------------------

    result = await db.execute(
        select(Appointment)
        .options(
            selectinload(
                Appointment.patient
            )
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.clinic_id == clinic_id,
        )
        .order_by(
            Appointment.created_at.desc()
        )
        .limit(10)
    )

    recent_rows = result.scalars().all()

    recent_appointments = [
        DoctorDashboardAppointment(
            id=a.id,
            patient_id=a.patient_id,
            patient_name=(
                a.patient.full_name
                if a.patient
                else f"Patient #{a.patient_id}"
            ),
            scheduled_at=a.scheduled_at,
            status=a.status.value,
        )
        for a in recent_rows
    ]

    # ---------------------------------
    # TODAY SCHEDULE
    # ---------------------------------

    result = await db.execute(
        select(Appointment)
        .options(
            selectinload(
                Appointment.patient
            )
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.clinic_id == clinic_id,
            Appointment.scheduled_at >= start_of_day,
            Appointment.scheduled_at < end_of_day,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        .order_by(
            Appointment.scheduled_at.asc()
        )
    )

    today_rows = result.scalars().all()

    today_schedule = [
        DoctorDashboardAppointment(
            id=a.id,
            patient_id=a.patient_id,
            patient_name=(
                a.patient.full_name
                if a.patient
                else f"Patient #{a.patient_id}"
            ),
            scheduled_at=a.scheduled_at,
            status=a.status.value,
        )
        for a in today_rows
    ]

    # ---------------------------------
    # RECENT PATIENTS
    # ---------------------------------

    seen_patients = set()

    recent_patients = []

    for appointment in recent_rows:

        if appointment.patient_id in seen_patients:
            continue

        seen_patients.add(
            appointment.patient_id
        )

        recent_patients.append(
            DoctorDashboardRecentPatient(
                patient_id=appointment.patient_id,
                patient_name=(
                    appointment.patient.full_name
                    if appointment.patient
                    else f"Patient #{appointment.patient_id}"
                ),
                last_visit=appointment.scheduled_at,
            )
        )


    today_revenue = (
        await get_doctor_revenue_today(
            db=db,
            doctor_id=doctor_id,
            clinic_id=clinic_id,
        )
    )

    month_revenue = (
        await get_doctor_revenue_this_month(
            db=db,
            doctor_id=doctor_id,
            clinic_id=clinic_id,
        )
    )

    consultation_completion_rate = (
        await get_completion_rate(
            db=db,
            doctor_id=doctor_id,
            clinic_id=clinic_id,
        )
    )

    return DoctorDashboardResponse(
        today_appointments=today_appointments,
        upcoming_appointments=upcoming_appointments,
        pending_appointments=pending_appointments,
        completed_today=completed_today,
        cancelled_today=cancelled_today,

        today_revenue=today_revenue,
        month_revenue=month_revenue,
        consultation_completion_rate=(
            consultation_completion_rate
        ),
        
        recent_appointments=recent_appointments,
        today_schedule=today_schedule,
        recent_patients=recent_patients,
    )