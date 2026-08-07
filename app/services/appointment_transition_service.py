from sqlalchemy.ext.asyncio import AsyncSession
import logging
from app.schemas.event_metadata import EventActor
from app.models.appointment import Appointment, AppointmentStatus
from app.models.user import UserRole
from app.schemas.event_metadata import EventSource
from app.domain.fsm.appointment_transition import transition_appointment
from app.services.appointment_audit_service import log_appointment_transition
from app.try_except.exceptions import ConflictError,ForbiddenError
from sqlalchemy.orm.exc import StaleDataError
from datetime import datetime
from app.core.time import UTC
from app.utils.db_retry import with_retry

from app.services.appointment_side_effects import (
    handle_appointment_transition_side_effects,
)

from app.services.domain_event_service import (
    publish_domain_event,
)

from app.schemas.event import (
    AppointmentStatusChangedEvent,
)

from opentelemetry import trace
from opentelemetry.trace import (
    Status,
    StatusCode,
)

from app.core.tracing import (
    inject_trace_attributes,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


QUEUE_DASHBOARD_STATUSES = {
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.WAITING,
    AppointmentStatus.IN_CONSULTATION,
    AppointmentStatus.COMPLETED,
}


async def transition_appointment_locked(
    *,
    db: AsyncSession,
    appointment: Appointment,
    new_status: AppointmentStatus,
    changed_by: int,
    actor_role: UserRole,
    actor_doctor_id: int | None = None,
    emit_event: bool = False,
    correlation_id: str | None = None,
    # Declared by the caller rather than inferred from changed_by being None.
    # The inference would work today — every user-initiated caller passes a
    # real id and only the no-show job passes None — but it reads "nobody is
    # recorded" as "the system did it", and those are different statements. A
    # future caller with no user to attribute would silently stop notifying.
    source: EventSource = EventSource.USER,

) -> Appointment:
    
    old_status = appointment.status

    try:
    
        with tracer.start_as_current_span(
            "transition_appointment_locked"
        ) as span:
            
            inject_trace_attributes(
                user_id=changed_by,
                appointment_id=appointment.id,
            )

            span.set_attribute(
                "appointment_id",
                appointment.id,
            )

            span.set_attribute(
                "old_status",
                str(appointment.status),
            )

            span.set_attribute(
                "new_status",
                str(new_status),
            )

            span.set_attribute(
                "changed_by",
                changed_by,
            )

            span.set_attribute(
                "actor_role",
                actor_role.name,
            )

            span.set_attribute(
                "emit_event",
                emit_event,
            )

            span.set_attribute(
                "correlation_id",
                correlation_id or "",
            )

            

            if actor_role == UserRole.DOCTOR and actor_doctor_id is not None:
                if appointment.doctor_id != actor_doctor_id:
                    raise ForbiddenError("Not your appointment")
                
        
            #old_status = appointment.status

            if old_status == new_status:
                return appointment


            async def _run():

                # 1️⃣ FSM
                await transition_appointment(
                    #db=db,
                    appointment=appointment,
                    new_status=new_status,
                    #changed_by=changed_by,
                )

                # 2️⃣ LOG
                logger.info(
                    "appointment_transition",
                    extra={
                        "appointment_id": appointment.id,
                        "from": str(old_status),
                        "to": str(new_status),
                        "changed_by": changed_by,
                    }
                )

                # 3️⃣ TIMESTAMPS
               
                now = datetime.now(UTC)
                occurred_at = now.isoformat()

                if new_status == AppointmentStatus.CONFIRMED:
                    appointment.confirmed_at = appointment.confirmed_at or now

                elif new_status == AppointmentStatus.CHECKED_IN:
                    appointment.checked_in_at = (
                        appointment.checked_in_at or now
                    )

                elif new_status == AppointmentStatus.WAITING:
                    appointment.waiting_started_at = (
                        appointment.waiting_started_at or now
                    )

                elif new_status == AppointmentStatus.IN_CONSULTATION:
                    appointment.consultation_started_at = (
                        appointment.consultation_started_at or now
                    )
                   

                elif new_status == AppointmentStatus.COMPLETED:
                    appointment.completed_at = (
                        appointment.completed_at or now
                    )
                  

                elif new_status == AppointmentStatus.CANCELLED:
                    appointment.cancelled_at = (
                        appointment.cancelled_at or now
                    )
                 

                # 4️⃣ AUDIT
                await log_appointment_transition(
                    db=db,
                    appointment_id=appointment.id,
                    from_status=old_status,
                    to_status=new_status,
                    changed_by=changed_by,
                )

                

                # 5️⃣ OUTBOX
                if emit_event:

                    actor = (
                        EventActor(
                            id=changed_by,
                            role=actor_role.name,
                        )
                        if changed_by is not None
                        else None
                    )

                    event = AppointmentStatusChangedEvent(
                        event_type="APPOINTMENT_STATUS_CHANGED",

                        schema_version=1,
                        occurred_at=occurred_at,
                        source=source,

                        aggregate_type="appointment",
                        aggregate_id=appointment.id,

                        correlation_id=correlation_id,
                        causation_id=None,
                        actor=actor,

                        patient_id=appointment.patient_id,
                        appointment_id=appointment.id,
                        doctor_id=appointment.doctor_id,
                        changed_by=changed_by,
                        new_status=new_status.value,
                    )

                    await publish_domain_event(
                        db=db,
                        event=event,
                    )
                    
            

                await db.flush()


                await handle_appointment_transition_side_effects(
                    db=db,
                    appointment=appointment,
                    new_status=new_status,
                )

                return appointment

        
            result =  await with_retry(
                _run,
                db,
                operation="appointment_transition",
            )


            span.set_status(
                Status(StatusCode.OK)
            )

            return result
        

        
    
    except StaleDataError as e:

        span.record_exception(e)

        span.set_status(
            Status(
                StatusCode.ERROR,
                "stale_data_conflict",
            )
        )

        raise ConflictError(
            "Appointment was modified by another user"
        )

    # =========================
    # GENERIC FAILURE
    # =========================

    except Exception as e:

        span = trace.get_current_span()

        span.record_exception(e)

        span.set_status(
            Status(
                StatusCode.ERROR,
                str(e),
            )
        )

        raise


