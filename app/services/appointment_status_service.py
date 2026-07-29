from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import UserRole,User
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor, DoctorStatus
from app.core.time import UTC
from app.core.time import _ensure_utc
from app.try_except.exceptions import ForbiddenError,BadRequestError
from app.services.appointment_transition_service import transition_appointment_locked




async def confirm_appointment(
    *,
    db: AsyncSession,
    appointment: Appointment,
    doctor: Doctor,
):
     # 1️⃣ Doctor must be verified
    if doctor.status != DoctorStatus.APPROVED:
        raise ForbiddenError("Doctor not verified")

    # 1️⃣ Ownership check
    if appointment.doctor_id != doctor.id:
        raise ForbiddenError("Not your appointment")

    # 2️⃣ Time validation
    if _ensure_utc(appointment.scheduled_at) <= datetime.now(UTC):
        raise BadRequestError("Cannot confirm appointment after start time")
    
    # Already confirmed
    if appointment.status != AppointmentStatus.PENDING:
        raise BadRequestError(
            f"Cannot confirm appointment in {appointment.status.value} state"
        )

    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CONFIRMED,
        changed_by=doctor.user_id,
        actor_role=UserRole.DOCTOR,
        actor_doctor_id=doctor.id,
        emit_event=True,
    )

    # await db.flush()
    # await db.refresh(appointment)

    return appointment



async def check_in_patient(
    *,
    db: AsyncSession,
    appointment: Appointment,
    current_user: User,
):
    """
    Reception staff marks the patient as arrived.

    CONFIRMED -> CHECKED_IN
    """

    if current_user.role not in (
        UserRole.RECEPTIONIST,
        UserRole.ADMIN,
        UserRole.DOCTOR,
    ):
        raise ForbiddenError(
            "You are not allowed to check in patients."
        )

    if appointment.status != AppointmentStatus.CONFIRMED:
        raise BadRequestError(
            f"Cannot check in appointment in {appointment.status.value} state"
        )

    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CHECKED_IN,
        changed_by=current_user.id,
        actor_role=current_user.role,
        emit_event=True,
    )

    # await db.flush()
    # await db.refresh(appointment)

    return appointment



async def move_to_waiting(
    *,
    db: AsyncSession,
    appointment: Appointment,
    current_user: User,
):
    """
    Move a checked-in patient into the doctor's waiting queue.

    CHECKED_IN -> WAITING
    """

    if current_user.role not in (
        UserRole.RECEPTIONIST,
        UserRole.ADMIN,
        UserRole.DOCTOR,
    ):
        raise ForbiddenError(
            "You are not allowed to manage the waiting queue."
        )

    if appointment.status != AppointmentStatus.CHECKED_IN:
        raise BadRequestError(
            f"Cannot move appointment to waiting from {appointment.status.value}"
        )

    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.WAITING,
        changed_by=current_user.id,
        actor_role=current_user.role,
        emit_event=True,
    )

    # await db.flush()
    # await db.refresh(appointment)

    return appointment




async def complete_appointment(
    *,
    db: AsyncSession,
    appointment: Appointment,
    doctor: Doctor,
):
    # 1️⃣ Doctor must be verified
    if doctor.status != DoctorStatus.APPROVED:
        raise ForbiddenError("Doctor not verified")
    
    # 2️⃣ Ownership check
    if appointment.doctor_id != doctor.id:
        raise ForbiddenError("Not your appointment")

    # scheduled_at = _ensure_utc(appointment.scheduled_at)
    # appointment_end = scheduled_at + timedelta(minutes=30)

    # if datetime.now(UTC) < appointment_end:
    #     raise BadRequestError("Appointment not finished yet")

    # if appointment.status != AppointmentStatus.CONFIRMED:
    #     raise BadRequestError(
    #         f"Cannot complete appointment in {appointment.status.value} state"
    #     )
    
    if appointment.status != AppointmentStatus.IN_CONSULTATION:
        raise BadRequestError(
            f"Cannot complete appointment in {appointment.status.value} state"
        )

    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.COMPLETED,
        changed_by=doctor.user_id,
        actor_role=UserRole.DOCTOR,
        actor_doctor_id=doctor.id,
        emit_event=True,
    )

    # await db.flush()
    # await db.refresh(appointment)

    return appointment




