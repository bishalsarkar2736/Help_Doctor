from datetime import datetime
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.time import UTC
from app.core.metrics import prescriptions_issued_total
from app.services.prescription_allergy_service import (
    MIN_ALLERGY_OVERRIDE_REASON,
    apply_override_state,
    validate_prescription_allergies,
)
from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)
from app.models.doctor import Doctor
from app.models.prescription import (
    Prescription,
    PrescriptionItem,
    PrescriptionStatus,
)
from app.models.user import UserRole,User
from app.schemas.event import (
    PrescriptionCreatedEvent,
    PrescriptionIssuedEvent,
    PrescriptionUpdatedEvent,
)
from app.schemas.prescription import (
    PrescriptionCreate,
    PrescriptionUpdate,
)
from app.services.appointment_transition_service import (
    transition_appointment_locked,
)
from app.services.domain_event_service import (
    publish_domain_event,
)
from app.try_except.audit import (
    log_audit_event,
)
from app.try_except.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)

from app.services.prescription_policy import (
    ensure_prescription_editable,
    ensure_prescription_issuable,
)

from app.services.activity_log_service import (
    log_activity,
)

from app.models.enums.activity_action import (
    ActivityAction,
)

from app.services.prescription_template_apply_service import (
    get_template_items,
)

# Shortest acceptable justification for prescribing through an allergy warning.
# Long enough to exclude "ok" / "x" / "n/a" — a trail full of those is no better
# than no reason at all — while staying short enough not to obstruct a
# prescriber acting in an emergency.
# Re-exported: tests and other services import it from here, and the constant
# belongs with the validation rule that enforces it.
__all__ = ["MIN_ALLERGY_OVERRIDE_REASON"]


async def _ensure_issuable_against_allergies(
    *,
    db: AsyncSession,
    prescription: Prescription,
    actor_user_id: int,
) -> None:
    """Re-check the allergy position at the moment the prescription becomes real.

    A draft can be written when the patient has no recorded allergy and issued
    after one is added. Issuing is when the document starts governing what
    somebody takes, so it is checked again here.

    Issuing carries no override fields, deliberately. A prescriber who needs to
    proceed anyway goes back to the draft and records the reason there, which
    keeps every justification on the prescription instead of creating a second
    place overrides can come from. The message says so, because a block with no
    stated way forward is a dead end.
    """
    items = (
        await db.scalars(
            select(PrescriptionItem).where(
                PrescriptionItem.prescription_id == prescription.id
            )
        )
    ).all()

    try:
        await validate_prescription_allergies(
            db=db,
            patient_user_id=prescription.patient_id,
            items=items,
            previously_justified=prescription.allergy_override_substances,
            actor_user_id=actor_user_id,
            prescription=prescription,
            # Nothing is being overridden here — this path only blocks or
            # passes, so there is no override to record.
            audit=False,
        )
    except BadRequestError as exc:
        raise BadRequestError(
            f"{exc.message} Edit the draft to record a clinical reason, then "
            "issue it."
        ) from exc


async def create_prescription(
    db: AsyncSession,
    doctor: Doctor,
    appointment_id: int,
    data: PrescriptionCreate,
):
    doctor_id = doctor.id
    doctor_user_id = doctor.user_id


    appointment = await db.get(
        Appointment,
        appointment_id,
    )

    if not appointment:
        raise NotFoundError(
            "Appointment not found"
        )

    if appointment.clinic_id != doctor.clinic_id:
        raise ForbiddenError(
            "Appointment belongs to another clinic"
        )

    if appointment.doctor_id != doctor.id:
        raise ForbiddenError(
            "Not your appointment"
        )

    if appointment.status not in [
        AppointmentStatus.IN_CONSULTATION,
        AppointmentStatus.COMPLETED,
    ]:
        raise BadRequestError(
            "Consultation not started"
        )

    existing = await db.execute(
        select(Prescription).where(
            Prescription.appointment_id
            == appointment_id,
            Prescription.clinic_id 
            == appointment.clinic_id,
        )
    )

    if existing.scalar_one_or_none():
        raise BadRequestError(
            "Prescription already exists"
        )

    # Template rows are loaded BEFORE the allergy check, not after it. They end
    # up on the prescription exactly like typed items, so they have to be part
    # of what is checked — previously they were added afterwards and a template
    # containing an allergen was never examined at all.
    template_items = []

    if data.template_id:
        template = await get_template_items(
            db=db,
            template_id=data.template_id,
            doctor_id=doctor_id,
            clinic_id=appointment.clinic_id,
        )
        template_items = list(template.items)

    # --- Allergy safety net: block prescribing a recorded allergen ---
    allergy_conflicts, generic_names, override_reason = (
        await validate_prescription_allergies(
            db=db,
            patient_user_id=appointment.patient_id,
            items=data.items,
            template_items=template_items,
            override=data.allergy_override,
            override_reason=data.allergy_override_reason,
            actor_user_id=doctor_user_id,
        )
    )

    prescription = Prescription(
        appointment_id=appointment_id,
        doctor_id=doctor_id,
        patient_id=appointment.patient_id,
        clinic_id=appointment.clinic_id,
        notes=data.notes,
        status=PrescriptionStatus.DRAFT,
    )

    apply_override_state(
        prescription, allergy_conflicts, generic_names, override_reason
    )

    db.add(prescription)

    await db.flush()

    for item in template_items:
        db.add(
            PrescriptionItem(
                prescription_id=prescription.id,
                medicine_name=item.medicine_name,
                dosage=item.dosage,
                frequency=item.frequency,
                duration_days=item.duration_days,
                instructions=item.instructions,
            )
        )

    items = [
        PrescriptionItem(
            prescription_id=prescription.id,
            medicine_name=item.medicine_name,
            medicine_id=item.medicine_id,
            dosage=item.dosage,
            frequency=item.frequency,
            duration_days=item.duration_days,
            instructions=item.instructions,
        )
        for item in data.items
    ]

    db.add_all(items)

    await db.flush()

    await log_audit_event(
        db=db,
        event_type="prescription",
        action="create",
        user_id=doctor_user_id,
        resource="prescription",
        details={
            "appointment_id": appointment_id,
        },
    )

    # The override audit record is written by validate_prescription_allergies,
    # so create, edit, revision and issue all produce the same trail.

    event = PrescriptionCreatedEvent(
        event_type="PRESCRIPTION_CREATED",
        schema_version=1,
        occurred_at=datetime.now(
            UTC
        ).isoformat(),
        aggregate_type="prescription",
        aggregate_id=prescription.id,
        correlation_id=None,
        causation_id=None,
        actor={
            "id": doctor_user_id,
            "role": UserRole.DOCTOR.name,
        },
        prescription_id=prescription.id,
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_id=doctor_id,
    )

    await publish_domain_event(
        db=db,
        event=event,
    )

    await db.refresh(
        prescription,
        attribute_names=["items"],
    )

    return prescription


async def get_active_draft_revision(
    db: AsyncSession,
    prescription: Prescription,
) -> Prescription:
    root_id = (
        prescription.parent_prescription_id
        or prescription.id
    )

    result = await db.execute(
        select(Prescription)
        .where(
            Prescription.clinic_id == prescription.clinic_id,
            (
                (Prescription.id == root_id)
                | (
                    Prescription.parent_prescription_id
                    == root_id
                )
            ),
            Prescription.is_latest_revision.is_(True),
        )
        .order_by(Prescription.revision_number.desc())
    )

    revision = result.scalar_one_or_none()

    if not revision:
        raise NotFoundError("Latest revision not found")

    if revision.status != PrescriptionStatus.DRAFT:
        raise BadRequestError(
            "Only draft revisions can be issued"
        )

    return revision



async def issue_prescription(
    *,
    db: AsyncSession,
    prescription: Prescription,
    transition_appointment: bool = True,
):

    doctor = await db.get(
        Doctor,
        prescription.doctor_id,
    )

    if not doctor:
        raise NotFoundError(
            "Doctor not found"
        )

    doctor_user_id = doctor.user_id

    ensure_prescription_issuable(
        prescription
    )

    item_count = await db.scalar(
        select(func.count(PrescriptionItem.id))
        .where(
            PrescriptionItem.prescription_id
            == prescription.id
        )
    )

    if not item_count:
        raise BadRequestError(
            "Cannot issue empty prescription"
        )

    await _ensure_issuable_against_allergies(
        db=db,
        prescription=prescription,
        actor_user_id=doctor_user_id,
    )

    appointment_result = await db.execute(
        select(Appointment).where(
            Appointment.id
            == prescription.appointment_id,
            Appointment.doctor_id 
            == prescription.doctor_id,
            Appointment.clinic_id 
            == prescription.clinic_id,
        )
    )

    appointment = (
        appointment_result.scalar_one_or_none()
    )

    if not appointment:
        raise NotFoundError(
            "Appointment not found"
        )

    if transition_appointment:
        if (
            appointment.status
            != AppointmentStatus.IN_CONSULTATION
        ):
            raise BadRequestError(
                "Appointment must be in consultation"
            )
    elif appointment.status not in [
        AppointmentStatus.IN_CONSULTATION,
        AppointmentStatus.COMPLETED,
    ]:
        raise BadRequestError(
            "Appointment must be in consultation or already completed"
        )

    prescription.status = (
        PrescriptionStatus.ISSUED
    )

    prescription.issued_at = datetime.now(
        UTC
    )

    prescriptions_issued_total.inc()

    if transition_appointment:
        await transition_appointment_locked(
            db=db,
            appointment=appointment,
            new_status=AppointmentStatus.COMPLETED,
            changed_by=doctor_user_id,
            actor_role=UserRole.DOCTOR,
            actor_doctor_id=appointment.doctor_id,
            emit_event=True,
        )

    await db.flush()

    await log_audit_event(
        db=db,
        event_type="prescription",
        action="issue",
        user_id=doctor_user_id,
        resource="prescription",
        details={
            "prescription_id":
            prescription.id,
            "appointment_id":
            prescription.appointment_id,
        },
    )

    event = PrescriptionIssuedEvent(
        event_type="PRESCRIPTION_ISSUED",
        schema_version=1,
        occurred_at=datetime.now(
            UTC
        ).isoformat(),
        aggregate_type="prescription",
        aggregate_id=prescription.id,
        correlation_id=None,
        causation_id=None,
        actor={
            "id": doctor_user_id,
            "role": UserRole.DOCTOR.name,
        },
        prescription_id=prescription.id,
        appointment_id=prescription.appointment_id,
        patient_id=prescription.patient_id,
        doctor_id=prescription.doctor_id,
        issued_at=prescription.issued_at.isoformat(),
    )

    await publish_domain_event(
        db=db,
        event=event,
    )

    await log_activity(
        db=db,
        clinic_id=prescription.clinic_id,
        actor_id=doctor.user_id,
        action=ActivityAction.PRESCRIPTION_ISSUED,
        entity_type="prescription",
        entity_id=prescription.id,
    )

    return prescription



async def get_prescription_by_id(
    db: AsyncSession,
    prescription_id: int,
    user: User,
):
    query = (
        select(Prescription)
        .options(
            selectinload(Prescription.items),
            selectinload(Prescription.doctor)
                .selectinload(Doctor.user),
            selectinload(Prescription.patient),
            selectinload(Prescription.appointment),
        )
        .where(
            Prescription.id == prescription_id,
        )
    )

    prescription = await db.scalar(query)

    if not prescription:
        raise NotFoundError(
            "Prescription not found"
        )

    if user.role == UserRole.DOCTOR:

        doctor = await db.scalar(
            select(Doctor).where(
                Doctor.user_id == user.id
            )
        )

        if not doctor:
            raise NotFoundError(
                "Doctor profile not found"
            )

        if (
            prescription.clinic_id
            != doctor.clinic_id
        ):
            raise ForbiddenError(
                "Cross-clinic access denied"
            )

        if (
            prescription.doctor_id
            != doctor.id
        ):
            raise ForbiddenError(
                "Not allowed"
            )

    elif user.role == UserRole.PATIENT:

        if (
            prescription.patient_id
            != user.id
        ):
            raise ForbiddenError(
                "Not allowed"
            )

    elif user.role == UserRole.ADMIN:
        pass

    else:
        raise ForbiddenError(
            "Not allowed"
        )

    return prescription


async def get_patient_prescriptions(
    db: AsyncSession,
    patient_id: int,
):

    result = await db.execute(
        select(Prescription)
        .options(
            selectinload(
                Prescription.items
            ),
            selectinload(
                Prescription.doctor
            ).selectinload(
                Doctor.user
            ),
            selectinload(
                Prescription.patient
            ),
            selectinload(
                Prescription.appointment
            ),
        )
        .where(
            Prescription.patient_id == patient_id,
            # Patients only see finalized, current prescriptions —
            # never drafts (doctor WIP) or superseded old revisions.
            Prescription.is_latest_revision.is_(True),
            Prescription.status != PrescriptionStatus.DRAFT,
        )
        .order_by(
            Prescription.created_at.desc()
        )
    )

    return result.scalars().all()


async def get_doctor_prescriptions(
    db: AsyncSession,
    doctor: Doctor,
    limit: int = 50,
    offset: int = 0,
):
    result = await db.execute(
        select(Prescription)
        .options(
            selectinload(Prescription.items),
            selectinload(Prescription.doctor)
                .selectinload(Doctor.user),
            selectinload(Prescription.patient),
            selectinload(Prescription.appointment),
        )
        .where(
            Prescription.doctor_id == doctor.id,
            Prescription.clinic_id == doctor.clinic_id,
        )
        .order_by(
            Prescription.created_at.desc()
        )
        .limit(limit)
        .offset(offset)
    )

    return result.scalars().all()



async def get_appointment_prescription(
    db: AsyncSession,
    appointment_id: int,
    user: User,
):
    query = (
        select(Prescription)
        .options(
            selectinload(Prescription.items),
            selectinload(Prescription.doctor)
                .selectinload(Doctor.user),
            selectinload(Prescription.patient),
            selectinload(Prescription.appointment),
        )
    )

    if user.role == UserRole.DOCTOR:

        doctor = await db.scalar(
            select(Doctor).where(
                Doctor.user_id == user.id
            )
        )

        if not doctor:
            raise NotFoundError(
                "Doctor profile not found"
            )

        prescription = await db.scalar(
            query.where(
                Prescription.appointment_id == appointment_id,
                Prescription.doctor_id == doctor.id,
                Prescription.clinic_id == doctor.clinic_id,
            )
        )

    elif user.role == UserRole.PATIENT:

        prescription = await db.scalar(
            query.where(
                Prescription.appointment_id == appointment_id,
                Prescription.patient_id == user.id,
            )
        )

    elif user.role == UserRole.ADMIN:

        prescription = await db.scalar(
            query.where(
                Prescription.appointment_id == appointment_id,
            )
        )

    else:
        raise ForbiddenError(
            "Not allowed"
        )

    if not prescription:
        raise NotFoundError(
            "Prescription not found"
        )

    return prescription



async def update_prescription(
    *,
    db: AsyncSession,
    prescription: Prescription,
    data: PrescriptionUpdate,
):
    doctor = await db.get(
        Doctor,
        prescription.doctor_id,
    )

    if not doctor:
        raise NotFoundError(
            "Doctor not found"
        )

    doctor_user_id = doctor.user_id

    ensure_prescription_editable(
        prescription
    )

    if not data.items:
        raise BadRequestError(
            "Prescription must contain at least one medicine"
        )

    # Checked BEFORE anything is written. An edit can introduce an allergen the
    # draft did not contain, and the patient's allergy list can change while a
    # draft sits unedited — either way this is the same decision as prescribing
    # it in the first place, and it went entirely unchecked before.
    allergy_conflicts, generic_names, override_reason = (
        await validate_prescription_allergies(
            db=db,
            patient_user_id=prescription.patient_id,
            items=data.items,
            override=data.allergy_override,
            override_reason=data.allergy_override_reason,
            # Conflicts already justified on this prescription do not need a
            # fresh reason, so adjusting a dosage does not re-prompt.
            previously_justified=prescription.allergy_override_substances,
            actor_user_id=doctor_user_id,
            prescription=prescription,
        )
    )

    apply_override_state(
        prescription, allergy_conflicts, generic_names, override_reason
    )

    prescription.notes = data.notes

    existing_items = await db.execute(
        select(PrescriptionItem).where(
            PrescriptionItem.prescription_id
            == prescription.id
        )
    )

    for item in existing_items.scalars():
        await db.delete(item)

    new_items = [
        PrescriptionItem(
            prescription_id=prescription.id,
            medicine_name=item.medicine_name,
            medicine_id=item.medicine_id,
            dosage=item.dosage,
            frequency=item.frequency,
            duration_days=item.duration_days,
            instructions=item.instructions,
        )
        for item in data.items
    ]

    db.add_all(new_items)

    await db.flush()

    await log_audit_event(
        db=db,
        event_type="prescription",
        action="update",
        user_id=doctor_user_id,
        resource="prescription",
        details={
            "prescription_id":
            prescription.id,
        },
    )

    event = PrescriptionUpdatedEvent(
        event_type="PRESCRIPTION_UPDATED",
        schema_version=1,
        occurred_at=datetime.now(
            UTC
        ).isoformat(),
        aggregate_type="prescription",
        aggregate_id=prescription.id,
        correlation_id=None,
        causation_id=None,
        actor={
            "id": doctor_user_id,
            "role": UserRole.DOCTOR.name,
        },
        prescription_id=prescription.id,
        appointment_id=prescription.appointment_id,
        patient_id=prescription.patient_id,
        doctor_id=prescription.doctor_id,
    )

    await publish_domain_event(
        db=db,
        event=event,
    )

    await db.refresh(
        prescription,
        attribute_names=["items"],
    )

    return prescription

