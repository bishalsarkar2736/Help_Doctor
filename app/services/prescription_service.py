from datetime import datetime
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.time import UTC
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


async def create_prescription(
    db: AsyncSession,
    doctor: Doctor,
    appointment_id: int,
    data: PrescriptionCreate,
):
    doctor_id = doctor.id
    doctor_user_id = doctor.user_id


    appointment_result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.doctor_id == doctor.id,
            Appointment.clinic_id == doctor.clinic_id,
        )
    )

    appointment = (
        appointment_result.scalar_one_or_none()
    )

    if not appointment:
        raise BadRequestError(
            "Appointment not found"
        )

    if appointment.doctor_id != doctor_id:
        raise ForbiddenError(
            "Not allowed"
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

    prescription = Prescription(
        appointment_id=appointment_id,
        doctor_id=doctor_id,
        patient_id=appointment.patient_id,
        clinic_id=appointment.clinic_id,
        notes=data.notes,
        status=PrescriptionStatus.DRAFT,
    )

    db.add(prescription)

    await db.flush()

    # ====================================
    # TEMPLATE ITEMS
    # ====================================

    if data.template_id:

        template = await get_template_items(
            db=db,
            template_id=data.template_id,
            doctor_id=doctor_id,
            clinic_id=appointment.clinic_id,
        )

        for item in template.items:

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


async def issue_prescription(
    *,
    db: AsyncSession,
    prescription: Prescription,
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

    if (
        appointment.status
        != AppointmentStatus.IN_CONSULTATION
    ):
        raise BadRequestError(
            "Appointment must be in consultation"
        )

    prescription.status = (
        PrescriptionStatus.ISSUED
    )

    prescription.issued_at = datetime.now(
        UTC
    )

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
    )

    if user.role == UserRole.DOCTOR:

        doctor = await db.scalar(
            select(Doctor).where(
                Doctor.user_id == user.id
            )
        )

        if not doctor:
            raise NotFoundError("Doctor profile not found")

        prescription = await db.scalar(
            query.where(
                Prescription.id == prescription_id,
                Prescription.doctor_id == doctor.id,
                Prescription.clinic_id == doctor.clinic_id,
            )
        )

    elif user.role == UserRole.PATIENT:

        prescription = await db.scalar(
            query.where(
                Prescription.id == prescription_id,
                Prescription.patient_id == user.id,
            )
        )

    elif user.role == UserRole.ADMIN:

        prescription = await db.scalar(
            query.where(
                Prescription.id == prescription_id,
            )
        )

    else:
        raise ForbiddenError("Not allowed")

    if not prescription:
        raise NotFoundError("Prescription not found")

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
            Prescription.patient_id
            == patient_id,
            
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

