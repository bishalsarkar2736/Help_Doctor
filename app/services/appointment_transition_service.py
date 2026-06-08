from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.appointment import Appointment, AppointmentStatus
from app.models.user import UserRole
from app.domain.fsm.appointment_transition import transition_appointment
from app.services.appointment_audit_service import log_appointment_transition
from app.try_except.exceptions import ConflictError,ForbiddenError
from sqlalchemy.orm.exc import StaleDataError
from app.services.outbox_service import publish_event
from datetime import datetime
from app.core.time import UTC
from app.utils.db_retry import with_retry


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
                db=db,
                appointment=appointment,
                new_status=new_status,
                changed_by=changed_by,
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

            elif new_status == AppointmentStatus.COMPLETED:
                appointment.completed_at = appointment.completed_at or now

            elif new_status == AppointmentStatus.CANCELLED:
                appointment.cancelled_at = appointment.cancelled_at or now

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
                # await publish_event(
                #     db=db,
                #     event_type="APPOINTMENT_STATUS_CHANGED",
                #     payload={
                #         "appointment_id": appointment.id,
                #         "new_status": new_status.value,
                #         "changed_by": changed_by,
                #         "doctor_id": appointment.doctor_id,
                #         "patient_id": appointment.patient_id,
                #         "occurred_at": occurred_at,
                        
                #     }
                # )
                event = AppointmentStatusChangedEvent(
                    event_type="APPOINTMENT_STATUS_CHANGED",

                    schema_version=1,
                    occurred_at=occurred_at,

                    aggregate_type="appointment",
                    aggregate_id=appointment.id,

                    correlation_id=correlation_id,
                    causation_id=None,

                    actor={
                        "id": changed_by,
                        "role": actor_role.name,
                    },

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
    
    
    except StaleDataError:

        span = trace.get_current_span()

        span.record_exception(
            ConflictError(
                "Appointment was modified by another user"
            )
        )

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







