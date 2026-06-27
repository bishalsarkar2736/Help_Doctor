from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)
import json
from app.models.user import UserRole

from app.services.appointment_transition_service import (
    transition_appointment_locked,
)

from app.try_except.audit import log_audit_event

from datetime import datetime

from app.core.time import UTC

from app.schemas.event import (
    ConsultationStartedEvent,
)

from app.services.activity_log_service import (
    log_activity,
)

from app.models.enums.activity_action import (
    ActivityAction,
)

from app.services.domain_event_service import (
    publish_domain_event,
)


async def start_consultation(
    *,
    db: AsyncSession,
    appointment: Appointment,
    doctor_id: int,
    correlation_id: str | None = None,
):

    updated_appointment = await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.IN_CONSULTATION,
        changed_by=doctor_id,
        actor_role=UserRole.DOCTOR,
        actor_doctor_id=appointment.doctor_id,
        emit_event=True,
        correlation_id=correlation_id,
    )

    await log_audit_event(
        db=db,
        event_type="consultation",
        action="start",
        user_id=doctor_id,
        resource="appointment",
        details={
            "appointment_id": appointment.id,
        },
    )

    await log_activity(
        db=db,
        clinic_id=appointment.clinic_id,
        actor_id=doctor_id,
        action=ActivityAction.CONSULTATION_STARTED,
        entity_type="appointment",
        entity_id=appointment.id,
        details=json.dumps({
            "patient_id": appointment.patient_id,
            "doctor_id": appointment.doctor_id,
        }),
    )

    event = ConsultationStartedEvent(
        event_type="CONSULTATION_STARTED",

        schema_version=1,
        occurred_at=datetime.now(UTC).isoformat(),

        aggregate_type="appointment",
        aggregate_id=appointment.id,

        correlation_id=correlation_id,
        causation_id=None,

        actor={
            "id": doctor_id,
            "role": UserRole.DOCTOR.name,
        },

        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
    )


    await publish_domain_event(
        db=db,
        event=event,
    )

    return updated_appointment
