
import uuid
import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.prescription import (
    PrescriptionStatus,
)
from app.models.outbox_event import OutboxEvent
from app.models.audit_log import AuditLog

from app.schemas.prescription import (
    PrescriptionCreate,
    PrescriptionItemCreate,
    PrescriptionUpdate,
    PrescriptionItemUpdate,
)

from app.services.prescription_service import (
    create_prescription,
    issue_prescription,
    update_prescription,
)

from app.try_except.exceptions import (
    BadRequestError,
    ForbiddenError,
)

from sqlalchemy import delete
from app.models.prescription import PrescriptionItem

from app.schemas.prescription import (
    PrescriptionResponse,
)


@pytest.mark.asyncio
async def test_create_prescription_success(
    db,
    doctor,
    doctor_user,
    patient_user,
    appointment_factory,
):

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    data = PrescriptionCreate(
        notes="Patient has fever",
        items=[
            PrescriptionItemCreate(
                medicine_name="Napa",
                dosage="500mg",
                frequency="2 times daily",
                duration_days=5,
                instructions="After meal",
            )
        ],
    )

    prescription = await create_prescription(
        db=db,
        doctor=doctor,  # FIXED
        appointment_id=appointment.id,
        data=data,
    )

    await db.commit()

    assert prescription.status == PrescriptionStatus.DRAFT
    assert prescription.patient_id == patient_user.id
    assert len(prescription.items) == 1


@pytest.mark.asyncio
async def test_create_prescription_requires_consultation(
    db,
    doctor,
    patient_user,
    appointment_factory,
):

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.CONFIRMED,
    )

    data = PrescriptionCreate(
        notes="Test",
        items=[
            PrescriptionItemCreate(
                medicine_name="Napa",
            )
        ],
    )

    with pytest.raises(BadRequestError):

        await create_prescription(
            db=db,
            doctor=doctor,  # FIXED
            appointment_id=appointment.id,
            data=data,
        )


@pytest.mark.asyncio
async def test_create_prescription_wrong_doctor(
    db,
    doctor,
    another_doctor,
    patient_user,
    appointment_factory,
):

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    data = PrescriptionCreate(
        notes="Test",
        items=[
            PrescriptionItemCreate(
                medicine_name="Napa",
            )
        ],
    )

    with pytest.raises(ForbiddenError):

        await create_prescription(
            db=db,
            doctor=another_doctor,  # FIXED
            appointment_id=appointment.id,
            data=data,
        )


@pytest.mark.asyncio
async def test_duplicate_prescription_not_allowed(
    db,
    doctor,
    patient_user,
    appointment_factory,
):

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    data = PrescriptionCreate(
        notes="Test",
        items=[
            PrescriptionItemCreate(
                medicine_name="Napa",
            )
        ],
    )

    await create_prescription(
        db=db,
        doctor=doctor,  # FIXED
        appointment_id=appointment.id,
        data=data,
    )

    with pytest.raises(BadRequestError):

        await create_prescription(
            db=db,
            doctor=doctor,  # FIXED
            appointment_id=appointment.id,
            data=data,
        )


@pytest.mark.asyncio
async def test_issue_prescription_success(
    db,
    doctor,
    prescription_factory,
    appointment_factory,
    doctor_user,
    patient_user,
):

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        status=PrescriptionStatus.DRAFT,
    )

    await issue_prescription(
        db=db,
        prescription=prescription,
    )

    await db.commit()

    assert prescription.status == PrescriptionStatus.ISSUED
    assert prescription.issued_at is not None

    await db.refresh(appointment)

    assert appointment.status == AppointmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_update_draft_prescription_success(
    db,
    doctor,
    prescription_factory,
    patient_user,
):

    prescription = await prescription_factory(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        status=PrescriptionStatus.DRAFT,
    )

    data = PrescriptionUpdate(
        notes="Updated notes",
        items=[
            PrescriptionItemUpdate(
                medicine_name="Ace",
                dosage="500mg",
                frequency="3x",
                duration_days=7,
                instructions="Before meal",
            )
        ],
    )

    updated = await update_prescription(
        db=db,
        prescription=prescription,
        data=data,
    )

    await db.commit()

    assert updated.notes == "Updated notes"
    assert len(updated.items) == 1
    assert updated.items[0].medicine_name == "Ace"


@pytest.mark.asyncio
async def test_issued_prescription_not_editable(
    db,
    doctor,
    prescription_factory,
    patient_user,
):

    prescription = await prescription_factory(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        status=PrescriptionStatus.ISSUED,
    )

    data = PrescriptionUpdate(
        notes="Updated",
        items=[
            PrescriptionItemUpdate(
                medicine_name="Ace",
            )
        ],
    )

    with pytest.raises(BadRequestError):

        await update_prescription(
            db=db,
            prescription=prescription,
            data=data,
        )


@pytest.mark.asyncio
async def test_prescription_created_event_emitted(
    db,
    doctor,
    patient_user,
    appointment_factory,
):

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    data = PrescriptionCreate(
        notes="Event test",
        items=[
            PrescriptionItemCreate(
                medicine_name="Napa",
            )
        ],
    )

    await create_prescription(
        db=db,
        doctor=doctor,  # FIXED
        appointment_id=appointment.id,
        data=data,
    )

    await db.commit()

    result = await db.execute(
        select(OutboxEvent).where(
            OutboxEvent.event_type == "PRESCRIPTION_CREATED"
        )
    )

    event = result.scalar_one()

    assert event.event_type == "PRESCRIPTION_CREATED"


@pytest.mark.asyncio
async def test_prescription_update_audit_created(
    db,
    doctor,
    prescription_factory,
    patient_user,
):

    prescription = await prescription_factory(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        status=PrescriptionStatus.DRAFT,
    )

    data = PrescriptionUpdate(
        notes="Audit update",
        items=[
            PrescriptionItemUpdate(
                medicine_name="Napa",
            )
        ],
    )

    await update_prescription(
        db=db,
        prescription=prescription,
        data=data,
    )

    await db.commit()

    result = await db.execute(
        select(AuditLog).where(
            AuditLog.action == "update"
        )
    )

    audit = result.scalar_one()

    assert audit.resource == "prescription"



@pytest.mark.asyncio
async def test_update_prescription_requires_items(
    db,
    doctor,
    prescription_factory,
    patient_user,
):

    prescription = await prescription_factory(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        status=PrescriptionStatus.DRAFT,
    )

    data = PrescriptionUpdate(
        notes="Updated",
        items=[],
    )

    with pytest.raises(BadRequestError):

        await update_prescription(
            db=db,
            prescription=prescription,
            data=data,
        )



@pytest.mark.asyncio
async def test_cannot_issue_empty_prescription(
    db,
    doctor,
    prescription_factory,
    appointment_factory,
    patient_user,
):

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        status=PrescriptionStatus.DRAFT,
        with_items = False,
    )

    await db.execute(
        delete(PrescriptionItem).where(
            PrescriptionItem.prescription_id
            == prescription.id
        )
    )

    await db.flush()

    with pytest.raises(BadRequestError):

        await issue_prescription(
            db=db,
            prescription=prescription,
        )


@pytest.mark.asyncio
async def test_prescription_has_uuid(
    db,
    doctor,
    patient_user,
    appointment_factory,
):

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    data = PrescriptionCreate(
        notes="UUID test",
        items=[
            PrescriptionItemCreate(
                medicine_name="Napa",
            )
        ],
    )

    prescription_1 = await create_prescription(
        db=db,
        doctor=doctor,
        appointment_id=appointment.id,
        data=data,
    )

    appointment_2 = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    prescription_2 = await create_prescription(
        db=db,
        doctor=doctor,
        appointment_id=appointment_2.id,
        data=data,
    )

    await db.commit()

    # ====================================
    # UUID EXISTS
    # ====================================

    assert prescription_1.uuid is not None
    assert prescription_2.uuid is not None

    # ====================================
    # UUID TYPE VALID
    # ====================================

    assert isinstance(
        prescription_1.uuid,
        uuid.UUID,
    )

    assert isinstance(
        prescription_2.uuid,
        uuid.UUID,
    )

    # ====================================
    # UUID UNIQUE
    # ====================================

    assert (
        prescription_1.uuid
        != prescription_2.uuid
    )

    # ====================================
    # RESPONSE SERIALIZATION
    # ====================================

    response = PrescriptionResponse.model_validate(
        prescription_1
    )

    assert response.uuid == prescription_1.uuid