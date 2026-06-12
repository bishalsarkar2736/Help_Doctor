from datetime import datetime
from app.core.time import UTC

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import logging
from sqlalchemy.exc import IntegrityError, DBAPIError
from app.models.patient import Patient
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.user import User, UserRole
from app.try_except.exceptions import ForbiddenError,BadRequestError,NotFoundError
from app.services.appointment_transition_service import transition_appointment_locked
from app.try_except.audit import log_audit_event
from app.core.cache import delete_cache
from app.domain.scheduling.slots import validate_exact_slot
from app.domain.scheduling.availability import validate_doctor_availability
from app.utils.db_retry import with_retry
from app.services.domain_event_service import (
    publish_domain_event,
)

from app.services.clinic_context_service import (
    get_current_clinic,
)

from app.schemas.event import (
    AppointmentCancelledEvent,
    AppointmentRescheduledEvent,
    AppointmentRescheduleRequestEvent,
    AppointmentCreatedEvent,
    AppointmentConfirmedEvent,
    CancelledByInfo,
)
from app.schemas.event_metadata import (
    EventActor,
)

from app.schemas.event import (
    CancelledByInfo,
)

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.tracing import (
    inject_trace_attributes,
)

from app.utils.event_ids import new_event_id

from app.core.metrics import (
    appointment_created_total,
    appointment_confirmed_total,
    appointment_cancelled_total,
    appointment_rescheduled_total,
    doctor_double_booking_prevented_total,
    doctor_slot_validation_failures_total,
)



logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)





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


async def get_appointment_by_id(
    db: AsyncSession,
    appointment_id: int,
    user: User,
) -> Appointment:

    result = await db.execute(
        select(Appointment)
        .options(
            selectinload(Appointment.doctor)
            .selectinload(Doctor.user),

            selectinload(Appointment.patient)
            .selectinload(Patient.user),
        )
        .where(Appointment.id == appointment_id)
    )

    appointment = result.scalar_one_or_none()

    if not appointment:
        raise NotFoundError("Appointment not found")

    # =========================
    # SECURITY CHECK
    # =========================
    if user.role == UserRole.PATIENT:

        if appointment.patient_id != user.id:
            raise ForbiddenError("Not your appointment")

    elif user.role == UserRole.DOCTOR:

        doctor = await _get_verified_doctor_by_user_id(
            db,
            user.id,
        )

        if appointment.doctor_id != doctor.id:
            raise ForbiddenError("Not your appointment")

    return appointment


# =========================
# CANCEL SIDE EFFECTS
# =========================
async def apply_cancellation_side_effects(
    *,
    db: AsyncSession,
    appointment: Appointment,
    cancelled_by: User,
    doctor: Doctor | None = None,
    reason: str | None = None,
    notify_patient: bool = False,
    notify_doctor: bool = False,
    correlation_id: str | None = None,
):
    # 1. Persist domain state
    appointment.cancel_reason = reason
    appointment.cancelled_by = cancelled_by.id

    await db.flush()

    now = datetime.now(UTC).isoformat()

    events = []
    
    # =========================
    # 2️⃣ Resolve doctor STRICTLY if needed
    # =========================
    if notify_doctor:
        if doctor is None:
            doctor = await db.get(Doctor, appointment.doctor_id)

        if doctor is None:
            raise NotFoundError("Doctor not found for cancellation side effect") 
    
        

    if notify_patient:

        events.append(
            AppointmentCancelledEvent(
                event_type="APPOINTMENT_CANCELLED",

                occurred_at=now,

                aggregate_type="appointment",
                aggregate_id=appointment.id,

                correlation_id=correlation_id,

                actor=EventActor(
                    id=cancelled_by.id,
                    role=cancelled_by.role.name,
                ),

                user_id=appointment.patient_id,

                appointment_id=appointment.id,

                cancelled_by=CancelledByInfo(
                    id=cancelled_by.id,
                    role=cancelled_by.role.name,
                ),

                reason=reason or "",
            )
        )

    if notify_doctor and doctor:

        events.append(
            AppointmentCancelledEvent(
                event_type="APPOINTMENT_CANCELLED",

                occurred_at=now,

                aggregate_type="appointment",
                aggregate_id=appointment.id,

                correlation_id=correlation_id,

                actor=EventActor(
                    id=cancelled_by.id,
                    role=cancelled_by.role.name,
                ),

                user_id=doctor.user_id,

                appointment_id=appointment.id,

                cancelled_by=CancelledByInfo(
                    id=cancelled_by.id,
                    role=cancelled_by.role.name,
                ),

                reason=reason or "",
            )
        )


    for event in events:

        await publish_domain_event(
            db=db,
            event=event,
        )


# =========================
# RESCHEDULE SIDE EFFECTS
# =========================
async def apply_reschedule_side_effects(
    *,
    db: AsyncSession,
    appointment: Appointment,
    actor: User,
    doctor: Doctor | None = None,
    notify_patient: bool = False,
    notify_doctor: bool = False,
    is_request: bool = False,
    correlation_id: str | None = None,
):
    now = datetime.now(UTC).isoformat()

    events = []

    # =========================
    # Resolve doctor if needed
    # =========================
    if notify_doctor:
        if doctor is None:
            doctor = await db.get(Doctor, appointment.doctor_id)

        if doctor is None:
            raise NotFoundError("Doctor not found for reschedule side effect")
        

        

    if notify_patient:

        events.append(
            AppointmentRescheduledEvent(
                event_type="APPOINTMENT_RESCHEDULED",

                occurred_at=now,

                aggregate_type="appointment",
                aggregate_id=appointment.id,

                correlation_id=correlation_id,

                actor=EventActor(
                    id=actor.id,
                    role=actor.role.name,
                ),

                user_id=appointment.patient_id,
                appointment_id=appointment.id,
            )
        )

    if notify_doctor and doctor:

        if is_request:

             events.append(
                AppointmentRescheduleRequestEvent(
                    event_type="APPOINTMENT_RESCHEDULE_REQUEST",

                    occurred_at=now,

                    aggregate_type="appointment",
                    aggregate_id=appointment.id,

                    correlation_id=correlation_id,

                    actor=EventActor(
                        id=actor.id,
                        role=actor.role.name,
                    ),

                    user_id=doctor.user_id,
                    appointment_id=appointment.id,
                )
            )

        else:

            events.append(
                AppointmentRescheduledEvent(
                    event_type="APPOINTMENT_RESCHEDULED",

                    occurred_at=now,

                    aggregate_type="appointment",
                    aggregate_id=appointment.id,

                    correlation_id=correlation_id,

                    actor=EventActor(
                        id=actor.id,
                        role=actor.role.name,
                    ),

                    user_id=doctor.user_id,
                    appointment_id=appointment.id,
                )
            )

    for event in events:

        await publish_domain_event(
            db=db,
            event=event,
        )



async def apply_booking_side_effects(
    *,
    db: AsyncSession,
    appointment: Appointment,
    doctor: Doctor,
    correlation_id: str | None = None,
):
    now = datetime.now(UTC).isoformat()

    if doctor is None:
        raise NotFoundError("Doctor not found for booking side effect")

    events = [

        AppointmentCreatedEvent(
            event_type="APPOINTMENT_CREATED",

            occurred_at=now,

            aggregate_type="appointment",
            aggregate_id=appointment.id,

            correlation_id=correlation_id,

            actor=EventActor(
                id=appointment.patient_id,
                role="PATIENT",
            ),

            user_id=appointment.patient_id,

            appointment_id=appointment.id,

            doctor_id=doctor.id,

            scheduled_at=(
                appointment.scheduled_at.isoformat()
            ),
        ),

        AppointmentCreatedEvent(
            event_type="APPOINTMENT_CREATED",

            occurred_at=now,

            aggregate_type="appointment",
            aggregate_id=appointment.id,

            correlation_id=correlation_id,

            actor=EventActor(
                id=appointment.patient_id,
                role="PATIENT",
            ),

            user_id=doctor.user_id,

            appointment_id=appointment.id,

            doctor_id=doctor.id,

            scheduled_at=(
                appointment.scheduled_at.isoformat()
            ),
        ),
    ]
    
    for event in events:

        await publish_domain_event(
            db=db,
            event=event,
        )



async def apply_confirmation_side_effects(
    *,
    db: AsyncSession,
    appointment: Appointment,
    doctor: Doctor,
    actor:User,
    correlation_id: str | None = None,
):
    now = datetime.now(UTC).isoformat()

    if doctor is None:
        raise NotFoundError("Doctor not found for confirmation side effect")

    events = [
        
        AppointmentConfirmedEvent(
            event_type="APPOINTMENT_CONFIRMED",

            occurred_at=now,

            aggregate_type="appointment",
            aggregate_id=appointment.id,

            correlation_id=correlation_id,

            actor=EventActor(
                id=actor.id,
                role=actor.role.name,
            ),

            user_id=appointment.patient_id,

            appointment_id=appointment.id,
        ),

        AppointmentConfirmedEvent(
            event_type="APPOINTMENT_CONFIRMED",

            occurred_at=now,

            aggregate_type="appointment",
            aggregate_id=appointment.id,

            correlation_id=correlation_id,

            actor=EventActor(
                id=actor.id,
                role=actor.role.name,
            ),

            user_id=doctor.user_id,

            appointment_id=appointment.id,
        ),
    ]
    for event in events:

        await publish_domain_event(
            db=db,
            event=event,
        )


# Booking


# =========================
# INTERNAL FUNCTION (DO NOT CALL DIRECTLY)
# =========================
async def _book_appointment_internal(
    db: AsyncSession,
    patient: User,
    doctor_id: int,
    scheduled_at: datetime,
) -> tuple [Appointment, Doctor]:
    
    doctor_result = await db.execute(
        select(Doctor)
        .where(Doctor.id == doctor_id)
        .with_for_update()
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


    try:
        validate_exact_slot(scheduled_at)

    except Exception:
        doctor_slot_validation_failures_total.labels(
            reason="invalid_slot"
        ).inc()
        raise


    try:
        await validate_doctor_availability(
            db,
            doctor.id,
            scheduled_at,
        )

    except Exception:
        doctor_slot_validation_failures_total.labels(
            reason="outside_availability"
        ).inc()
        raise
    
    clinic = await get_current_clinic(db)

    # 5️⃣ Create appointment
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient.id,
        clinic_id=clinic.id if clinic else None,
        scheduled_at=scheduled_at,
        status=AppointmentStatus.PENDING,
    )

    db.add(appointment)

    try:
        await db.flush()  # triggers exclusion constraint

    except IntegrityError:
        raise BadRequestError(
            "Doctor already booked for this time slot"
        )

    except DBAPIError as e:
        # 🚫 DO NOT rollback here
        # retry system will handle deadlock
        raise
        
        
    

    return appointment

# =========================
# PUBLIC FUNCTION (USE THIS)
# =========================
async def book_appointment(
    db: AsyncSession,
    patient: User,
    doctor_id: int,
    scheduled_at: datetime,
    correlation_id: str | None = None,
) -> Appointment:
    
    with tracer.start_as_current_span(
        "book_appointment"
    ) as span:
        
        inject_trace_attributes(
            user_id=patient.id,
        )
        
        try:

            span.set_attribute(
                "patient_id",
                patient.id,
            )

            span.set_attribute(
                "doctor_id",
                doctor_id,
            )

            span.set_attribute(
                "scheduled_at",
                scheduled_at.isoformat(),
            )
        
            # =========================
            # CREATE CORRELATION ID ONCE
            # =========================
            if correlation_id is None:
                correlation_id = new_event_id()
            
            span.set_attribute(
                "correlation_id",
                correlation_id,
            )

            async def _run():
                return await _book_appointment_internal(
                    db=db,
                    patient=patient,
                    doctor_id=doctor_id,
                    scheduled_at=scheduled_at,
                )

            #return await with_retry(_run, db)
            appointment = await with_retry(
                _run,
                db,
                operation="book_appointment",
            )

            await db.refresh(appointment)

            inject_trace_attributes(
                user_id=patient.id,
                appointment_id=appointment.id,
            )

            span.set_attribute(
                "appointment_id",
                appointment.id,
            )

            doctor = await db.get(
                Doctor,
                appointment.doctor_id,
            )

            await apply_booking_side_effects(
                db=db,
                appointment=appointment,
                doctor=doctor,
                correlation_id=correlation_id,
            )

            #await emit_appointment_event(db, appointment,doctor=doctor)

            await log_audit_event(
                db=db,
                event_type="appointment",
                user_id=patient.id,
                action="create",
                resource="appointment",
                details={
                    "appointment_id": appointment.id,
                    "doctor_id": doctor_id,
                    "scheduled_at": scheduled_at.isoformat(),
                    "correlation_id": correlation_id,
                },
            )

            appointment_date = scheduled_at.date()
            await delete_cache(f"doctor:{doctor_id}:slots:{appointment_date}")

            span.set_status(
                Status(StatusCode.OK)
            )

            appointment_created_total.inc()

            return appointment
        
        except Exception as e:

            span.record_exception(e)

            span.set_status(
                Status(
                    StatusCode.ERROR,
                    str(e),
                )
            )

            raise


    

# Patient


async def get_patient_appointments(db: AsyncSession, user: User):
    if user.role != UserRole.PATIENT:
        raise ForbiddenError("Only patients allowed")

    result = await db.execute(
        select(Appointment)
        # .join(Doctor, Appointment.doctor_id == Doctor.id)
        .options(
            selectinload(Appointment.doctor).selectinload(Doctor.user)
        )
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
    correlation_id: str | None = None,
):
    

    if correlation_id is None:
        correlation_id = new_event_id()

    if user.role != UserRole.PATIENT:
        raise ForbiddenError("Only patients allowed")
    
    result = await db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
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
        correlation_id=correlation_id,
    )

    doctor = await db.get(Doctor, appointment.doctor_id)

    # if doctor:
    await apply_cancellation_side_effects(
        db=db,
        appointment=appointment,
        cancelled_by=user,
        doctor=doctor,
        notify_doctor=True,
        correlation_id=correlation_id,
    )

    appointment_date = appointment.scheduled_at.date()
    await delete_cache(f"doctor:{appointment.doctor_id}:slots:{appointment_date}")

        
    #await emit_appointment_event(db, appointment,doctor=doctor)

    appointment_cancelled_total.labels(
        actor="PATIENT"
    ).inc()

    return appointment




async def patient_reschedule_appointment(
    db: AsyncSession,
    user: User,
    appointment_id: int,
    new_datetime: datetime,
    correlation_id: str | None = None,
):
    
    if correlation_id is None:
        correlation_id = new_event_id()


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
    

    old_date = appointment.scheduled_at.date()  # read old date BEFORE updating

    try:
        validate_exact_slot(new_datetime)

    except Exception:
        doctor_slot_validation_failures_total.labels(
            reason="invalid_slot"
        ).inc()
        raise

    if new_datetime < datetime.now(UTC):

        doctor_slot_validation_failures_total.labels(
            reason="past_time"
        ).inc()

        raise BadRequestError("Cannot reschedule appointment in the past")

    try:
        await validate_doctor_availability(
            db,
            appointment.doctor_id,
            new_datetime,
        )

    except Exception:
        doctor_slot_validation_failures_total.labels(
            reason="outside_availability"
        ).inc()
        raise


    # 🔁 Update schedule (this triggers exclusion constraint safely)
    try:
        appointment.scheduled_at = new_datetime
        await db.flush()

    except IntegrityError:

        doctor_double_booking_prevented_total.inc()

        raise BadRequestError("Doctor already booked for this time slot")


    # 🔁 Transition inside SAME transaction
    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.PENDING,
        changed_by=user.id,
        actor_role=user.role,
        correlation_id=correlation_id,
    )

    # Notifications after commit
    doctor = await db.get(Doctor, appointment.doctor_id)

    await apply_reschedule_side_effects(
        db=db,
        appointment=appointment,
        doctor=doctor,
        notify_doctor=True,
        is_request=True,
        correlation_id=correlation_id,
    )


    new_date = new_datetime.date()

    await delete_cache(f"doctor:{appointment.doctor_id}:slots:{old_date}")
    await delete_cache(f"doctor:{appointment.doctor_id}:slots:{new_date}")


    #await emit_appointment_event(db, appointment,doctor=doctor)

    appointment_rescheduled_total.labels(
        actor="PATIENT"
    ).inc()

    return appointment



# Doctor

async def doctor_update_appointment_status(
    db: AsyncSession,
    doctor_user: User,
    appointment_id: int,
    new_status: AppointmentStatus,
    correlation_id: str | None = None,
):
    
    if correlation_id is None:
        correlation_id = new_event_id()

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
    
    if appointment.doctor_id != doctor.id:
        raise ForbiddenError("Not your appointment")
    
    old_status = appointment.status.value

    # ✅ 1. Transition (IMPORTANT: assign to variable)
    appointment = await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=new_status,
        changed_by=doctor_user.id,
        actor_role=doctor_user.role,
        actor_doctor_id=doctor.id,
        correlation_id=correlation_id,
    )


    if new_status == AppointmentStatus.CONFIRMED:
        await apply_confirmation_side_effects(
            db=db,
            appointment=appointment,
            doctor=doctor,
            actor=doctor_user,
            correlation_id=correlation_id,
        )

        appointment_confirmed_total.labels(
            actor="DOCTOR"
        ).inc()

    # ✅ 2. Emit real-time event (NEW)
    #await emit_appointment_event(db, appointment,doctor=doctor)

    # ✅ 3. Return as before

    await log_audit_event(
        db=db,
        event_type="appointment",
        user_id=doctor_user.id,
        action="update_status",
        resource="appointment",
        details={
            "appointment_id": appointment.id,
            "doctor_id": doctor.id,
            "old_status": old_status,
            "new_status": new_status.value,
            "correlation_id": correlation_id,
        },
    )
    return appointment


async def doctor_cancel_appointment(
    db: AsyncSession,
    doctor_user: User,
    appointment_id: int,
    correlation_id: str | None = None,
):
    
    if correlation_id is None:
        correlation_id = new_event_id()

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
        correlation_id=correlation_id,
    )

    await apply_cancellation_side_effects(
        db=db,
        appointment=appointment,
        cancelled_by=doctor_user,
        doctor=doctor,
        notify_patient=True,
        correlation_id=correlation_id,
    )

    appointment_date = appointment.scheduled_at.date()
    await delete_cache(f"doctor:{appointment.doctor_id}:slots:{appointment_date}")

    #await emit_appointment_event(db, appointment,doctor=doctor)

    appointment_cancelled_total.labels(
        actor="DOCTOR"
    ).inc()

    return appointment




async def doctor_reschedule_appointment(
    db: AsyncSession,
    doctor_user: User,
    appointment_id: int,
    new_datetime: datetime,
    correlation_id: str | None = None,
):
    
    if correlation_id is None:
        correlation_id = new_event_id()

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

    old_date = appointment.scheduled_at.date()

    try:
        validate_exact_slot(new_datetime)

    except Exception:
        doctor_slot_validation_failures_total.labels(
            reason="invalid_slot"
        ).inc()
        raise

    if new_datetime < datetime.now(UTC):

        doctor_slot_validation_failures_total.labels(
            reason="past_time"
        ).inc()

        raise BadRequestError("Cannot reschedule appointment in the past")

    try:
        await validate_doctor_availability(
            db,
            appointment.doctor_id,
            new_datetime,
        )

    except Exception:
        doctor_slot_validation_failures_total.labels(
            reason="outside_availability"
        ).inc()

        raise

    try:
        appointment.scheduled_at = new_datetime
        await db.flush()

    except IntegrityError:

        doctor_double_booking_prevented_total.inc()

        doctor_slot_validation_failures_total.labels(
            reason="overlap"
        ).inc()

        raise BadRequestError("Doctor already booked for this time slot")

    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CONFIRMED,
        changed_by=doctor_user.id,
        actor_role=doctor_user.role,
        actor_doctor_id=doctor.id,
        correlation_id=correlation_id,
    )

    await apply_reschedule_side_effects(
        db=db,
        appointment=appointment,
        doctor=doctor,
        notify_patient=True,
        correlation_id=correlation_id,
    )

    # after flush + transition

    new_date = new_datetime.date()

    await delete_cache(f"doctor:{appointment.doctor_id}:slots:{old_date}")
    await delete_cache(f"doctor:{appointment.doctor_id}:slots:{new_date}")

    #await emit_appointment_event(db, appointment,doctor=doctor)

    appointment_rescheduled_total.labels(
        actor="DOCTOR"
    ).inc()

    return appointment


async def doctor_today_appointments(db: AsyncSession, user: User):
    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, user.id)

    now = datetime.now(UTC)
    today = now.date()

    start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(today, datetime.max.time(), tzinfo=UTC)

    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor.id,
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= end,
        )
        .order_by(Appointment.scheduled_at.asc(), Appointment.id.asc())
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
        .order_by(Appointment.scheduled_at.asc(), Appointment.id.asc())
    )

    return result.scalars().all()


async def doctor_pending_with_patient(
    db: AsyncSession,
    user: User,
    limit: int = 50,
    offset: int = 0,
):
    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, user.id)

    result = await db.execute(
        select(Appointment, User)
        .join(User, Appointment.patient_id == User.id)
        .where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.PENDING,
        )
        .order_by(Appointment.scheduled_at.asc(), Appointment.id.asc())
        .limit(limit)
        .offset(offset)
    )

    return result.all()


async def doctor_confirmed_appointments(db: AsyncSession, user: User):

    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, user.id)

    result = await db.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .order_by(Appointment.scheduled_at.asc(), Appointment.id.asc())
    )

    return result.scalars().all()


async def doctor_confirmed_with_patient(
    db: AsyncSession,
    user: User,
    limit: int = 50,
    offset: int = 0,
):
    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Doctor only")

    doctor = await _get_verified_doctor_by_user_id(db, user.id)

    result = await db.execute(
        select(Appointment, User)
        .join(User, Appointment.patient_id == User.id)
        .where(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .order_by(Appointment.scheduled_at.asc(), Appointment.id.asc())
        .limit(limit)
        .offset(offset)
    )

    return result.all()



# Admin


async def admin_force_cancel_appointment(
    db: AsyncSession,
    admin: User,
    appointment_id: int,
    reason: str,
    correlation_id: str | None = None,
):
    
    if correlation_id is None:
        correlation_id = new_event_id()

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
        emit_event=False,
        correlation_id=correlation_id,
    )

    doctor = await db.get(Doctor, appointment.doctor_id)
    

    await apply_cancellation_side_effects(
        db=db,
        appointment=appointment,
        cancelled_by=admin,
        doctor=doctor,
        reason=reason,
        notify_patient=True,
        notify_doctor=True,
        correlation_id=correlation_id,
    )

    appointment_date = appointment.scheduled_at.date()
    await delete_cache(f"doctor:{appointment.doctor_id}:slots:{appointment_date}")

    #await emit_appointment_event(db, appointment,doctor=doctor)

    # 🔥 CRITICAL FIX
    await db.flush()

    appointment_cancelled_total.labels(
        actor="ADMIN"
    ).inc()

    return appointment





