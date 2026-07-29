from sqlalchemy.ext.asyncio import AsyncSession

from app.services.waiting_queue_service import (
    get_next_waiting_patient
)
from app.services.domain_event_service import publish_domain_event

from app.schemas.event import PatientNextInQueueEvent

from datetime import datetime
from app.core.time import UTC


async def notify_next_patient(
    *,
    db: AsyncSession,
    doctor_id: int,
):
    """
    Publish a PATIENT_NEXT_IN_QUEUE event for the first waiting
    patient only once.
    """

    appointment = await get_next_waiting_patient(
        db=db,
        doctor_id=doctor_id,
    )

    if appointment is None:
        return


    event = PatientNextInQueueEvent(
        event_type="PATIENT_NEXT_IN_QUEUE",

        schema_version=1,
        occurred_at=datetime.now(UTC).isoformat(),

        aggregate_type="appointment",
        aggregate_id=appointment.id,

        correlation_id=None,
        causation_id=None,

        actor=None,

        patient_id=appointment.patient_id,
        appointment_id=appointment.id,
        doctor_id=appointment.doctor_id,
    )

    await publish_domain_event(
        db=db,
        event=event,
    )


