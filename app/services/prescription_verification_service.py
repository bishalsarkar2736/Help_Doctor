from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.doctor import Doctor
from app.models.prescription import (
    Prescription,
    PrescriptionStatus,
)
from app.try_except.exceptions import (
    BadRequestError,
    NotFoundError,
)

from app.schemas.prescription_verification import PrescriptionVerificationResponse


VERIFICATION_VALID = "VALID"
VERIFICATION_SUPERSEDED = "SUPERSEDED"

async def verify_prescription_by_uuid(
    *,
    db: AsyncSession,
    prescription_uuid: UUID,
):

    result = await db.execute(
        select(Prescription)
        .options(
            selectinload(Prescription.doctor)
                .selectinload(Doctor.user),
            selectinload(Prescription.clinic),
        )
        .where(
            Prescription.uuid
            == prescription_uuid
        )
    )

    prescription = (
        result.scalar_one_or_none()
    )

    if not prescription:
        raise NotFoundError(
            "Prescription not found"
        )

    if prescription.status not in [
        PrescriptionStatus.ISSUED,
        PrescriptionStatus.LOCKED,
        PrescriptionStatus.SUPERSEDED,
    ]:
        raise BadRequestError(
            "Prescription is not publicly verifiable"
        )

    doctor_name = (
        prescription.doctor.user.full_name
        if (
            prescription.doctor
            and prescription.doctor.user
            and prescription.doctor.user.full_name
        )
        else f"Doctor #{prescription.doctor_id}"
    )

    is_valid = (
        prescription.status
        == PrescriptionStatus.ISSUED
        and prescription.is_latest_revision
    )

    verification_status = (
        VERIFICATION_VALID
        if is_valid
        else VERIFICATION_SUPERSEDED
    )


    return PrescriptionVerificationResponse(
        valid=is_valid,
        verification_status=verification_status,
        prescription_uuid=prescription.uuid,
        prescription_id=prescription.id,
        appointment_id=prescription.appointment_id,
        patient_id=prescription.patient_id,
        doctor_id=prescription.doctor_id,
        doctor_name=doctor_name,

        clinic_name=(
            prescription.clinic.name
            if prescription.clinic
            else None
        ),

        clinic_logo_url=(
            prescription.clinic.logo_url
            if prescription.clinic
            else None
        ),

        status=prescription.status,
        issued_at=prescription.issued_at,
        revision_number=prescription.revision_number,
        is_latest_revision=prescription.is_latest_revision,
    )