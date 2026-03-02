from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.core.time import UTC
from app.core.time import _ensure_utc
from app.try_except.exceptions import ForbiddenError,BadRequestError
from app.domain.fsm.appointment_transition import transition_appointment


# def _assert_transition_allowed(
#     *,
#     appointment: Appointment,
#     target_status: AppointmentStatus,
# ):
#     current = appointment.status

#     if current in (
#         AppointmentStatus.CANCELLED,
#         AppointmentStatus.COMPLETED,
#     ):
#         raise BadRequestError("Appointment already closed")

#     if (
#         current == AppointmentStatus.SCHEDULED
#         and target_status != AppointmentStatus.CONFIRMED
#     ):
#         raise BadRequestError("Invalid appointment transition")

#     if (
#         current == AppointmentStatus.CONFIRMED
#         and target_status != AppointmentStatus.COMPLETED
#     ):
#         raise BadRequestError("Invalid appointment transition")



async def confirm_appointment(
    *,
    db: AsyncSession,
    appointment: Appointment,
    doctor: Doctor,
):
     # 1️⃣ Doctor must be verified
    if not doctor.is_verified:
        raise ForbiddenError("Doctor not verified")

    # 1️⃣ Ownership check
    if appointment.doctor_id != doctor.id:
        raise ForbiddenError("Not your appointment")

    # 2️⃣ Time validation
    if _ensure_utc(appointment.scheduled_at) <= datetime.now(UTC):
        raise BadRequestError("Cannot confirm appointment after start time")

    # 3️⃣ FSM handles invalid states
    await transition_appointment(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CONFIRMED,
        changed_by=doctor.user_id,
    )

    await db.flush()
    await db.refresh(appointment)

    return appointment




async def complete_appointment(
    *,
    db: AsyncSession,
    appointment: Appointment,
    doctor: Doctor,
):
    # 1️⃣ Doctor must be verified
    if not doctor.is_verified:
        raise ForbiddenError("Doctor not verified")
    
    # 2️⃣ Ownership check
    if appointment.doctor_id != doctor.id:
        raise ForbiddenError("Not your appointment")

    scheduled_at = _ensure_utc(appointment.scheduled_at)
    appointment_end = scheduled_at + timedelta(minutes=30)

    if datetime.now(UTC) < appointment_end:
        raise BadRequestError("Appointment not finished yet")

    # 🔥 Single transition call
    await transition_appointment(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.COMPLETED,
        changed_by=doctor.user_id,
    )

    await db.flush()
    await db.refresh(appointment)

    return appointment




