from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.models.appointment import Appointment, AppointmentStatus
from app.models.user import UserRole
from app.domain.fsm.appointment_transition import transition_appointment
from app.services.appointment_audit_service import log_appointment_transition
from app.try_except.exceptions import ConflictError, NotFoundError, ForbiddenError
from sqlalchemy.orm.exc import StaleDataError
from app.services.outbox_service import publish_event


logger = logging.getLogger(__name__)


async def transition_appointment_locked(
    *,
    db: AsyncSession,
    appointment: Appointment,
    new_status: AppointmentStatus,
    changed_by: int,
    actor_role: UserRole,  # keep for permission logic if needed
    actor_doctor_id: int | None = None,
) -> Appointment:

    if actor_doctor_id is not None and appointment.doctor_id != actor_doctor_id:
        raise ForbiddenError("Not your appointment")

    old_status = appointment.status

    # Idempotency: do nothing if same state
    if old_status == new_status:
        return appointment

    try:
        await transition_appointment(
            db=db,
            appointment=appointment,
            new_status=new_status,
            changed_by=changed_by,
        )
    # except ValueError as exc:
    #     raise ConflictError(str(exc))

        await log_appointment_transition(
            db=db,
            appointment_id=appointment.id,
            from_status=old_status,
            to_status=new_status,
            changed_by=changed_by,
        )

          # 3️⃣ Publish outbox event (NEW)
        await publish_event(
            db=db,
            event_type="APPOINTMENT_STATUS_CHANGED",
            payload={
                "appointment_id": appointment.id,
                "new_status": new_status.value,
                "changed_by": changed_by,
                "doctor_id": appointment.doctor_id,
                "patient_id": appointment.patient_id,
            }
        )

        await db.flush()

    except StaleDataError:
        raise ConflictError(
            "Appointment was modified by another user"
        )


    return appointment





