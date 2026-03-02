from app.models.appointment import AppointmentStatus,Appointment
from app.domain.audit.appointment_audit import record_status_change
from app.core.time import UTC
from datetime import datetime
from app.domain.fsm.appointment_fsm import AppointmentFSM
from sqlalchemy.ext.asyncio import AsyncSession


import logging

logger = logging.getLogger("app.appointment.transition")

async def transition_appointment(
    *,
    db: AsyncSession,
    appointment: Appointment,
    new_status: AppointmentStatus,
    changed_by: int | None,
    timestamp: datetime | None = None,
):
    """
    Centralized appointment state transition handler
    """

    old_status = appointment.status

    # Normalize in case status was loaded as string
    if isinstance(old_status, str):
        old_status = AppointmentStatus(old_status.upper())

    
    # 1️⃣ FSM validation (with logging)
    try:
        AppointmentFSM.can_transition(old_status, new_status)
    except Exception:
        logger.warning(
            "Invalid appointment transition attempt",
            extra={
                "appointment_id": appointment.id,
                "old_status": old_status.value,
                "attempted_status": new_status.value,
                "changed_by": changed_by,
            },
        )
        raise


    # 2️⃣ Log transition
    logger.info(
        "Appointment status transition",
        extra={
            "appointment_id": appointment.id,
            "old_status": old_status.value,
            "new_status": new_status.value,
            "changed_by": changed_by,
        },
    )

    # 2️⃣ Apply status
    appointment.status = new_status

    now = timestamp or datetime.now(UTC)

    # 3️⃣ Timestamp handling
    if new_status == AppointmentStatus.CONFIRMED:
        appointment.confirmed_at = now

    elif new_status == AppointmentStatus.COMPLETED:
        appointment.completed_at = now

    elif new_status == AppointmentStatus.CANCELLED:
        appointment.cancelled_at = now

    # 4️⃣ Audit trail
    # await record_status_change(
    #     db=db,
    #     appointment=appointment,
    #     old_status=old_status,
    #     new_status=new_status,
    #     changed_by=changed_by,
    # )

   # await db.flush()

    return appointment
