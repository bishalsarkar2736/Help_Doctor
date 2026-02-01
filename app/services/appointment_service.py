from datetime import datetime, date,UTC
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status

from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.doctor_availability import DoctorAvailability
from app.models.user import User, UserRole
from app.services.notification_service import notify_user


# =========================================================
# Helpers
# =========================================================

async def _get_verified_doctor(db: AsyncSession, user: User) -> Doctor:
    if user.role != UserRole.DOCTOR:
        raise HTTPException(403, "Only doctors allowed")

    result = await db.execute(
        select(Doctor).where(Doctor.user_id == user.id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor profile not found")

    if not doctor.is_verified:
        raise HTTPException(403, "Doctor not verified")

    return doctor


async def cancel_appointment(
    *,
    db: AsyncSession,
    appointment: Appointment,
    cancelled_by: User,
    reason: str | None = None,
    notify_patient: bool = False,
    notify_doctor: bool = False,
):
    if appointment.status in (
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
    ):
        raise HTTPException(400, "Appointment already closed")

    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancelled_by = cancelled_by.id
    appointment.cancel_reason = reason
    appointment.cancelled_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(appointment)

    if notify_patient:
        await notify_user(
            db=db,
            user_id=appointment.patient_id,
            title="Appointment Cancelled",
            message="Your appointment was cancelled",
            appointment_id=appointment.id,
        )

    if notify_doctor:
        await notify_user(
            db=db,
            user_id=appointment.doctor_id,
            title="Appointment Cancelled",
            message="An appointment was cancelled",
            appointment_id=appointment.id,
        )


    return appointment


# =========================================================
# Booking
# =========================================================

async def book_appointment(
    db: AsyncSession,
    patient: User,
    doctor_id: int,
    scheduled_at: datetime,
):
    if patient.role != UserRole.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can book appointments",
        )

    result = await db.execute(
        select(Doctor).where(
            Doctor.id == doctor_id,
            Doctor.is_verified.is_(True),
        )
    )
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(404, "Doctor not available")

    weekday = scheduled_at.weekday()
    appointment_time = scheduled_at.time()

    result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.doctor_id == doctor.id,
            DoctorAvailability.day_of_week == weekday,
            DoctorAvailability.start_time <= appointment_time,
            DoctorAvailability.end_time > appointment_time,
            DoctorAvailability.is_available.is_(True),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(400, "Doctor not available at this time")

    result = await db.execute(
        select(Appointment).where(
            and_(
                Appointment.doctor_id == doctor.id,
                Appointment.scheduled_at == scheduled_at,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(400, "Time slot already booked")

    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient.id,
        scheduled_at=scheduled_at,
    )

    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    return appointment


# =========================================================
# Patient
# =========================================================

async def get_patient_appointments(db: AsyncSession, user: User):
    if user.role != UserRole.PATIENT:
        raise HTTPException(403, "Only patients allowed")

    result = await db.execute(
        select(Appointment)
        .join(Doctor, Appointment.doctor_id == Doctor.id)
        .where(Appointment.patient_id == user.id)
        .order_by(Appointment.scheduled_at.desc())
    )

    appointments = result.scalars().all()

    return [
        {
            "id": a.id,
            "scheduled_at": a.scheduled_at,
            "status": a.status.value,
            "notes": a.notes,
            "doctor_name": a.doctor.user.full_name,
            "specialization": a.doctor.specialization,
        }
        for a in appointments
    ]


async def patient_cancel_appointment(db: AsyncSession, user: User, appointment_id: int):
    appointment = await db.get(Appointment, appointment_id)

    if not appointment or appointment.patient_id != user.id:
        raise HTTPException(403, "Not allowed")

    return await cancel_appointment(
        db=db,
        appointment=appointment,
        cancelled_by=user,
        notify_doctor=True,
    )


async def patient_reschedule_appointment(
    db: AsyncSession,
    user: User,
    appointment_id: int,
    new_datetime: datetime,
):
    appointment = await db.get(Appointment, appointment_id)

    if not appointment or appointment.patient_id != user.id:
        raise HTTPException(403, "Not allowed")

    if appointment.status in (
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
    ):
        raise HTTPException(400, "Cannot reschedule closed appointment")

    appointment.scheduled_at = new_datetime
    appointment.status = AppointmentStatus.PENDING

    await db.commit()
    await db.refresh(appointment)

    await notify_user(
    db=db,
    user_id=appointment.doctor_id,
    title="Appointment Reschedule Request",
    message="Patient requested appointment reschedule",
    appointment_id=appointment.id,
)


    return appointment


# =========================================================
# Doctor
# =========================================================

async def doctor_update_appointment_status(
    db: AsyncSession,
    doctor_user: User,
    appointment_id: int,
    new_status: AppointmentStatus,
):
    doctor = await _get_verified_doctor(db, doctor_user)

    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.doctor_id == doctor.id,
        )
    )
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise HTTPException(404, "Appointment not found")

    if appointment.status in (
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
    ):
        raise HTTPException(400, "Appointment already closed")

    appointment.status = new_status
    await db.commit()
    await db.refresh(appointment)

    return appointment


async def doctor_cancel_appointment(
    db: AsyncSession,
    doctor_user: User,
    appointment_id: int,
):
    doctor = await _get_verified_doctor(db, doctor_user)

    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.doctor_id == doctor.id,
        )
    )
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise HTTPException(404, "Appointment not found")

    return await cancel_appointment(
        db=db,
        appointment=appointment,
        cancelled_by=doctor_user,
        notify_patient=True,
    )


async def doctor_reschedule_appointment(
    db: AsyncSession,
    doctor_user: User,
    appointment_id: int,
    new_datetime: datetime,
):
    doctor = await _get_verified_doctor(db, doctor_user)

    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.doctor_id == doctor.id,
        )
    )
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise HTTPException(404, "Appointment not found")

    appointment.scheduled_at = new_datetime
    appointment.status = AppointmentStatus.CONFIRMED

    await db.commit()
    await db.refresh(appointment)

    await notify_user(
    db=db,
    user_id=appointment.patient_id,
    title="Appointment Rescheduled",
    message="Doctor rescheduled your appointment",
    appointment_id=appointment.id,
    )

    return appointment


async def doctor_today_appointments(db: AsyncSession, user: User):
    doctor = await _get_verified_doctor(db, user)
    today = date.today()

    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor.id,
            Appointment.scheduled_at >= datetime.combine(today, datetime.min.time()),
            Appointment.scheduled_at <= datetime.combine(today, datetime.max.time()),
        )
    )

    return result.scalars().all()


async def doctor_pending_appointments(db: AsyncSession, user: User):
    doctor = await _get_verified_doctor(db, user)

    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.PENDING,
        )
    )

    return result.scalars().all()


async def doctor_confirmed_appointments(db: AsyncSession, user: User):
    doctor = await _get_verified_doctor(db, user)

    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
    )

    return result.scalars().all()


# =========================================================
# Admin
# =========================================================

async def admin_force_cancel_appointment(
    db: AsyncSession,
    admin: User,
    appointment_id: int,
    reason: str,
):
    if admin.role != UserRole.ADMIN:
        raise HTTPException(403, "Admin only")

    appointment = await db.get(Appointment, appointment_id)
    if not appointment:
        raise HTTPException(404, "Appointment not found")

    return await cancel_appointment(
        db=db,
        appointment=appointment,
        cancelled_by=admin,
        reason=reason,
        notify_patient=True,
        notify_doctor=True,
    )
