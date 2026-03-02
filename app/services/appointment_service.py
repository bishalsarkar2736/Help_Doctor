from datetime import datetime, date, timedelta
from app.core.time import UTC

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.doctor_availability import DoctorAvailability
from app.models.user import User, UserRole
from app.services.notification_service import notify_user
from app.try_except.exceptions import ForbiddenError,BadRequestError,NotFoundError
from app.services.appointment_transition_service import transition_appointment_locked
from sqlalchemy.exc import IntegrityError


# Helpers

async def _get_verified_doctor_by_user_id(
    db: AsyncSession,
    user_id: int,
) -> Doctor:
    result = await db.execute(
        select(Doctor)
        .where(
            Doctor.user_id == user_id,
            Doctor.is_verified.is_(True),
        )
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise ForbiddenError("Doctor not verified")

    return doctor


async def get_current_verified_doctor(
    db: AsyncSession,
    user: User
) -> Doctor:

    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    return await _get_verified_doctor_by_user_id(db, user.id)



async def apply_cancellation_side_effects(
    *,
    db: AsyncSession,
    appointment: Appointment,
    cancelled_by: User,
    reason: str | None = None,
    notify_patient: bool = False,
    notify_doctor: bool = False,
):
    # Set metadata only (NO FSM here)
    appointment.cancel_reason = reason
    appointment.cancelled_by = cancelled_by.id

    if notify_patient:
        await notify_user(
            db=db,
            user_id=appointment.patient_id,
            title="Appointment Cancelled",
            message="Your appointment was cancelled",
            appointment_id=appointment.id,
        )

    if notify_doctor:
        doctor = await db.get(Doctor, appointment.doctor_id)

        if doctor:
            await notify_user(
                db=db,
                user_id=doctor.user_id,
                title="Appointment Cancelled",
                message="An appointment was cancelled",
                appointment_id=appointment.id,
            )



# Booking


APPOINTMENT_DURATION_MINUTES = 30

async def book_appointment(
    db: AsyncSession,
    patient: User,
    doctor_id: int,
    scheduled_at: datetime,
) -> Appointment:

    doctor_result = await db.execute(
        select(Doctor)
        .where(Doctor.id == doctor_id)
        #.with_for_update()
    )
    doctor = doctor_result.scalar_one_or_none()

    if not doctor:
        raise BadRequestError("Invalid doctor")

    if not doctor.is_verified:
        raise ForbiddenError("Doctor not verified")

    # 2️⃣ Role check
    if patient.role != UserRole.PATIENT:
        raise ForbiddenError("Only patients can book appointments")

    # 3️⃣ Past time check
    if scheduled_at < datetime.now(UTC):
        raise BadRequestError("Cannot book appointment in the past")

    # 4️⃣ Availability validation
    appointment_end = scheduled_at + timedelta(
        minutes=APPOINTMENT_DURATION_MINUTES
    )

    weekday = scheduled_at.weekday()
    start_time = scheduled_at.time()
    end_time = appointment_end.time()

    availability_result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.doctor_id == doctor.id,
            DoctorAvailability.is_available.is_(True),
        )
    )
    availabilities = availability_result.scalars().all()

    if not availabilities:
        raise BadRequestError("Doctor has no availability configured")

    if not any(
        a.day_of_week == weekday
        and a.start_time <= start_time
        and a.end_time >= end_time
        for a in availabilities
    ):
        raise BadRequestError("Doctor not available at this time") 

    # 5️⃣ Create appointment
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient.id,
        scheduled_at=scheduled_at,
        status=AppointmentStatus.PENDING,
    )

    db.add(appointment)

    try:
        await db.flush()  # triggers exclusion constraint
    except IntegrityError as e:
        #await db.rollback()
        raise BadRequestError(
            "Doctor already booked for this time slot"
        ) from e

    await db.refresh(appointment)

    return appointment
    
    

        



# Patient


async def get_patient_appointments(db: AsyncSession, user: User):
    if user.role != UserRole.PATIENT:
        raise ForbiddenError("Only patients allowed")

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


async def patient_cancel_appointment(
    db: AsyncSession,
    user: User,
    appointment_id: int,
):
    if user.role != UserRole.PATIENT:
        raise ForbiddenError("Only patients allowed")
    
    result = await db.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise NotFoundError("Appointment not found")

    if appointment.patient_id != user.id:
        raise ForbiddenError("Not your appointment")


    appointment = await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CANCELLED,
        changed_by=user.id,
        actor_role=user.role,
    )

    doctor = await db.get(Doctor, appointment.doctor_id)

    if doctor:
        await notify_user(
                db=db,
                user_id=doctor.user_id,
                title="Appointment Cancelled",
                message="Patient cancelled the appointment",
                appointment_id=appointment.id,
        )

    return appointment




async def patient_reschedule_appointment(
    db: AsyncSession,
    user: User,
    appointment_id: int,
    new_datetime: datetime,
):

    if user.role != UserRole.PATIENT:
        raise ForbiddenError("Only patients allowed")

    #async with db.begin():
    result = await db.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id)
            .with_for_update()
    )
    appointment = result.scalar_one_or_none()

    if not appointment or appointment.patient_id != user.id:
        raise ForbiddenError("Not allowed")

    if appointment.status in (
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
    ):
        raise BadRequestError("Cannot reschedule closed appointment")

    # 🔁 Update schedule (this triggers exclusion constraint safely)
    appointment.scheduled_at = new_datetime

    # 🔁 Transition inside SAME transaction
    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.PENDING,
        changed_by=user.id,
        actor_role=user.role,
    )

        

    # Notifications after commit
    doctor = await db.get(Doctor, appointment.doctor_id)

    if doctor:
        await notify_user(
            db=db,
            user_id=doctor.user_id,
            title="Appointment Reschedule Request",
            message="Patient requested appointment reschedule",
            appointment_id=appointment.id,
        )

    return appointment



# Doctor

async def doctor_update_appointment_status(
    db: AsyncSession,
    doctor_user_id: int,
    appointment_id: int,
    new_status: AppointmentStatus,
):

    # Fetch doctor user
    user_result = await db.execute(
        select(User).where(User.id == doctor_user_id)
    )
    doctor_user = user_result.scalar_one_or_none()

    if not doctor_user:
        raise BadRequestError("Invalid doctor")

    if doctor_user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, doctor_user.id)

    result = await db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
    )
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise NotFoundError("Appointment not found")

    return await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=new_status,
        changed_by=doctor_user.id,
        actor_role=doctor_user.role,
        actor_doctor_id=doctor.id,
    )


async def doctor_cancel_appointment(
    db: AsyncSession,
    doctor_user: User,
    appointment_id: int,
):

    if doctor_user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, doctor_user.id)

    result = await db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
    )
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise NotFoundError("Appointment not found")

    appointment = await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CANCELLED,
        changed_by=doctor_user.id,
        actor_role=doctor_user.role,
        actor_doctor_id=doctor.id,
    )

    await notify_user(
        db=db,
        user_id=appointment.patient_id,
        title="Appointment Cancelled",
        message="Doctor cancelled your appointment",
        appointment_id=appointment.id,
    )

    return appointment




async def doctor_reschedule_appointment(
    db: AsyncSession,
    doctor_user: User,
    appointment_id: int,
    new_datetime: datetime,
):

    if doctor_user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, doctor_user.id)

    result = await db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
    )
    appointment = result.scalar_one_or_none()

    if not appointment or appointment.doctor_id != doctor.id:
        raise NotFoundError("Appointment not found")

    #appointment.scheduled_at = new_datetime
    try:
        appointment.scheduled_at = new_datetime
        await db.flush()
    except IntegrityError:
        raise BadRequestError("Doctor already booked for this time slot")

    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CONFIRMED,
        changed_by=doctor_user.id,
        actor_role=doctor_user.role,
        actor_doctor_id=doctor.id,
    )

    await notify_user(
        db=db,
        user_id=appointment.patient_id,
        title="Appointment Rescheduled",
        message="Doctor rescheduled your appointment",
        appointment_id=appointment.id,
    )

    return appointment

async def doctor_today_appointments(db: AsyncSession, user: User):
    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, user.id)

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

    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, user.id)

    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.PENDING,
        )
    )

    return result.scalars().all()


async def doctor_confirmed_appointments(db: AsyncSession, user: User):

    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, user.id)

    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
    )

    return result.scalars().all()



# Admin


async def admin_force_cancel_appointment(
    db: AsyncSession,
    admin: User,
    appointment_id: int,
    reason: str,
):

    if admin.role != UserRole.ADMIN:
        raise ForbiddenError("Admin only")

    result = await db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
    )
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise NotFoundError("Appointment not found")

    appointment = await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CANCELLED,
        changed_by=admin.id,
        actor_role=admin.role,
    )

    appointment.cancel_reason = reason
    appointment.cancelled_by = admin.id

    await notify_user(
        db=db,
        user_id=appointment.patient_id,
        title="Appointment Cancelled by Admin",
        message="Your appointment was cancelled by admin",
        appointment_id=appointment.id,
    )

    doctor = await db.get(Doctor, appointment.doctor_id)

    if doctor:
        await notify_user(
            db=db,
            user_id=doctor.user_id,
            title="Appointment Cancelled by Admin",
            message="An appointment was cancelled by admin",
            appointment_id=appointment.id,
        )

    return appointment





