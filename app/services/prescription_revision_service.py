from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.time import UTC
from app.models.doctor import Doctor
from app.models.prescription import (
    Prescription,
    PrescriptionItem,
    PrescriptionStatus,
)
from app.models.user import UserRole
from app.schemas.event import (
    PrescriptionRevisedEvent,
)

from app.services.prescription_template_apply_service import (
    get_template_items,
)

from app.schemas.prescription import (
    PrescriptionRevisionCreate,
)

from app.services.domain_event_service import (
    publish_domain_event,
)

from app.try_except.audit import (
    log_audit_event,
)

from app.services.activity_log_service import (
    log_activity,
)

from app.models.enums.activity_action import (
    ActivityAction,
)

from app.try_except.exceptions import (
    BadRequestError,
    NotFoundError,
)

from app.schemas.event_metadata import EventActor


async def create_prescription_revision(
    *,
    db: AsyncSession,
    prescription: Prescription,
    doctor: Doctor,
    data: PrescriptionRevisionCreate,
):
    """
    Create immutable prescription revision.

    Flow:

    ISSUED (latest)
        ↓
    LOCKED
        ↓
    NEW DRAFT REVISION
    """

    clinic_id = prescription.clinic_id

    # ====================================================
    # VALIDATION
    # ====================================================

    if prescription.status != PrescriptionStatus.ISSUED:
        raise BadRequestError(
            "Only issued prescriptions can be revised"
        )

    if not prescription.is_latest_revision:
        raise BadRequestError(
            "Only latest revision can be revised"
        )

    if not data.items and not data.template_id:
        raise BadRequestError(
            "Prescription must contain at least one medicine"
        )

    # ====================================================
    # LOCK PRESCRIPTION ROW
    # ====================================================

    locked_result = await db.execute(
        select(Prescription)
        .where(
            Prescription.id == prescription.id,
            Prescription.clinic_id == clinic_id,
        )
        .with_for_update()
    )

    locked_prescription = (
        locked_result.scalar_one_or_none()
    )

    if not locked_prescription:
        raise NotFoundError(
            "Prescription not found"
        )

    prescription = locked_prescription

    # ====================================================
    # CONCURRENCY SAFETY
    # ====================================================

    latest_result = await db.execute(
        select(Prescription)
        .where(
            Prescription.appointment_id
            == prescription.appointment_id,

            Prescription.clinic_id== clinic_id,

            Prescription.is_latest_revision.is_(True),
        )
        .with_for_update()
    )

    latest = latest_result.scalar_one_or_none()

    if not latest:
        raise NotFoundError(
            "Latest prescription not found"
        )

    if latest.id != prescription.id:
        raise BadRequestError(
            "Another revision is being created concurrently"
        )

    # ====================================================
    # SUPERSEDE CURRENT REVISION
    # ====================================================

    prescription.status = (
        PrescriptionStatus.LOCKED
    )

    prescription.is_latest_revision = False

    await db.flush()

    # ====================================================
    # REVISION NUMBER
    # ====================================================

    root_id = (
        prescription.parent_prescription_id
        or prescription.id
    )

    latest_revision_number = await db.scalar(
        select(
            func.max(
                Prescription.revision_number
            )
        ).where(
            (
                (Prescription.id == root_id)
                |
                (
                    Prescription.parent_prescription_id
                    == root_id
                )
            ),
            Prescription.clinic_id
            == clinic_id,
        )
    )

    next_revision_number = (
        (latest_revision_number or 1) + 1
    )

    # ====================================================
    # CREATE NEW REVISION
    # ====================================================

    new_revision = Prescription(
        appointment_id=prescription.appointment_id,
        doctor_id=prescription.doctor_id,
        patient_id=prescription.patient_id,
        clinic_id=prescription.clinic_id,
        notes=data.notes,
        status=PrescriptionStatus.DRAFT,
        issued_at=None,
        parent_prescription_id=root_id,
        revision_number=next_revision_number,
        is_latest_revision=True,
    )

    db.add(new_revision)

    await db.flush()

    # ====================================
    # TEMPLATE ITEMS
    # ====================================

    if data.template_id:

        template = await get_template_items(
            db=db,
            template_id=data.template_id,
            doctor_id=doctor.id,
            clinic_id=clinic_id,
        )

        for item in template.items:

            db.add(
                PrescriptionItem(
                    prescription_id=new_revision.id,
                    medicine_name=item.medicine_name,
                    dosage=item.dosage,
                    frequency=item.frequency,
                    duration_days=item.duration_days,
                    instructions=item.instructions,
                )
            )

    # ====================================================
    # CREATE ITEMS
    # ====================================================

    items = [
        PrescriptionItem(
            prescription_id=new_revision.id,
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

    # ====================================================
    # AUDIT LOG
    # ====================================================

    await log_audit_event(
        db=db,
        event_type="prescription",
        action="revision_create",
        user_id=doctor.user_id,
        resource="prescription",
        details={
            "old_prescription_id": prescription.id,
            "new_prescription_id": new_revision.id,
            "revision_number": next_revision_number,
        },
    )

    # ====================================================
    # DOMAIN EVENT
    # ====================================================

    event = PrescriptionRevisedEvent(
        event_type="PRESCRIPTION_REVISED",
        schema_version=1,
        occurred_at=datetime.now(UTC).isoformat(),
        aggregate_type="prescription",
        aggregate_id=new_revision.id,
        correlation_id=None,
        causation_id=None,
        actor=EventActor(
            id=doctor.user_id,
            role=UserRole.DOCTOR.name,
        ),
        old_prescription_id=prescription.id,
        new_prescription_id=new_revision.id,
        appointment_id=new_revision.appointment_id,
        patient_id=new_revision.patient_id,
        doctor_id=new_revision.doctor_id,
        revision_number=new_revision.revision_number,
    )

    await publish_domain_event(
        db=db,
        event=event,
    )

    await log_activity(
        db=db,
        clinic_id=clinic_id,
        actor_id=doctor.user_id,
        action=ActivityAction.PRESCRIPTION_REVISED,
        entity_type="prescription",
        entity_id=new_revision.id,
        details=(
            f"Revision {next_revision_number} "
            f"created from prescription {prescription.id}"
        ),
    )

    # ====================================================
    # LOAD RELATIONSHIPS
    # ====================================================

    await db.refresh(
        new_revision,
        attribute_names=["items"],
    )

    return new_revision