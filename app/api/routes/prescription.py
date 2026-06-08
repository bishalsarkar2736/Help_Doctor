from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.schemas.prescription import (
    PrescriptionCreate,
    PrescriptionResponse,
)
from app.services.prescription_service import create_prescription
from app.security.rbac import require_roles
from app.models.user import User, UserRole
from app.try_except.exceptions import NotFoundError, ForbiddenError,BadRequestError
from app.models.prescription import Prescription,PrescriptionStatus
from app.services.prescription_service import (
    issue_prescription,
    get_prescription_by_id,
    get_patient_prescriptions,
    get_appointment_prescription,
    update_prescription,
)

from sqlalchemy.exc import IntegrityError

from sqlalchemy import select
from app.models.doctor import Doctor

from fastapi.responses import StreamingResponse

from app.services.pres_doctor_profile_service import (
    get_doctor_profile,
)

from io import BytesIO

from app.services.prescription_pdf_service import (
    generate_prescription_pdf,
)

from app.schemas.prescription import (
    PrescriptionUpdate,
    PrescriptionRevisionCreate,
    PrescriptionRevisionResponse,
    PrescriptionRevisionHistoryResponse
)

from app.try_except.audit import log_audit_event

from uuid import UUID

from app.schemas.prescription_verification import (
    PrescriptionVerificationResponse,
)

from app.services.prescription_verification_service import (
    verify_prescription_by_uuid,
)

from app.services.prescription_revision_service import (
    create_prescription_revision,
)

from app.services.prescription_history_service import (
    get_prescription_revision_history,
)

from app.utils.db_errors import (
    is_latest_revision_conflict,
)

from app.services.medicine_service import (
    get_existing_medicine_names,
)

from app.mappers.prescription_mapper import (
    to_prescription_response,
    to_prescription_revision_response,
)





router = APIRouter(
    prefix="/prescriptions",
    tags=["Prescriptions"],
)


@router.post(
    "/appointments/{appointment_id}",
    response_model=PrescriptionResponse,
)
async def create_prescription_endpoint(
    appointment_id: int,
    data: PrescriptionCreate,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    """
    Only DOCTOR can create prescription
    """

    result = await db.execute(
        select(Doctor).where(
            Doctor.user_id == doctor.id
        )
    )

    doctor_profile = result.scalar_one_or_none()

    if not doctor_profile:
        raise ForbiddenError("Doctor profile not found")

    prescription = await create_prescription(
        db=db,
        doctor=doctor_profile,
        appointment_id=appointment_id,
        data=data,
    )

    #return prescription

    medicine_names = [
        item.medicine_name
        for item in prescription.items
    ]

    existing_medicines = (
        await get_existing_medicine_names(
            db,
            medicine_names,
        )
    )

    return to_prescription_response(
        prescription,
        existing_medicines,
    )



@router.post("/{prescription_id}/issue")
async def issue_prescription_endpoint(
    prescription_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    prescription = await db.get(
        Prescription,
        prescription_id,
    )

    if not prescription:
        raise NotFoundError("Prescription not found")

    result = await db.execute(
        select(Doctor).where(
            Doctor.user_id == doctor.id
        )
    )

    doctor_profile = result.scalar_one_or_none()

    if not doctor_profile:
        raise ForbiddenError("Doctor profile not found")

    if prescription.doctor_id != doctor_profile.id:
        raise ForbiddenError("Not allowed")

    await issue_prescription(
        db=db,
        prescription=prescription,
    )

    await db.commit()

    return {
        "message": "prescription_issued"
    }


@router.post(
    "/{prescription_id}/revisions",
    response_model=PrescriptionRevisionResponse,
    status_code=201,
)
async def create_revision(
    prescription_id: int,
    data: PrescriptionRevisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    # ✅ SAFE: resolve doctor via DB (NOT relationship)
    result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise ForbiddenError("Doctor profile not found")

    prescription = await get_prescription_by_id(
        db=db,
        prescription_id=prescription_id,
    )

    if prescription.doctor_id != doctor.id:
        raise ForbiddenError("Not allowed")

    try:

        revision = await create_prescription_revision(
            db=db,
            prescription=prescription,
            doctor=doctor,
            data=data,
        )

        await db.commit()

        await db.refresh(revision)

        #return revision

        medicine_names = [
            item.medicine_name
            for item in revision.items
        ]

        existing_medicines = (
            await get_existing_medicine_names(
                db,
                medicine_names,
            )
        )

        return to_prescription_revision_response(
            revision,
            existing_medicines,
        )

    except IntegrityError as e:

        await db.rollback()

        if is_latest_revision_conflict(e):
            raise BadRequestError(
                "Another latest prescription already exists"
            )

        raise
    

    

@router.get(
    "/{prescription_id}/revisions/history",
    response_model=PrescriptionRevisionHistoryResponse,
)
async def get_revision_history(
    prescription_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    revisions = await get_prescription_revision_history(
        db=db,
        prescription_id=prescription_id,
    )

    return {
        "items": revisions
    }



@router.get(
    "/{prescription_id}",
    response_model=PrescriptionResponse,
)
async def get_prescription_endpoint(
    prescription_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(
        UserRole.DOCTOR,
        UserRole.PATIENT,
        UserRole.ADMIN,
    )),
):

    prescription = await get_prescription_by_id(
        db=db,
        prescription_id=prescription_id,
    )

    # RBAC ownership checks

    # if user.role == UserRole.DOCTOR:

    #     if not user.doctor:
    #         raise ForbiddenError("Doctor profile not found")

    #     if prescription.doctor_id != user.doctor.id:
    #         raise ForbiddenError("Not allowed")

    if user.role == UserRole.DOCTOR:

        result = await db.execute(
            select(Doctor).where(
                Doctor.user_id == user.id
            )
        )

        doctor_profile = result.scalar_one_or_none()

        if not doctor_profile:
            raise ForbiddenError(
                "Doctor profile not found"
            )

        if prescription.doctor_id != doctor_profile.id:
            raise ForbiddenError("Not allowed")

    elif user.role == UserRole.PATIENT:
        if prescription.patient_id != user.id:
            raise ForbiddenError("Not allowed")

    #return prescription

    medicine_names = [
        item.medicine_name
        for item in prescription.items
    ]

    existing_medicines = (
        await get_existing_medicine_names(
            db,
            medicine_names,
        )
    )

    return to_prescription_response(
        prescription,
        existing_medicines,
    )


@router.get(
    "/me",
    response_model=list[PrescriptionResponse],
)
async def my_prescriptions_endpoint(
    db: AsyncSession = Depends(get_db),
    patient: User = Depends(
        require_roles(UserRole.PATIENT)
    ),
):

    # return await get_patient_prescriptions(
    #     db=db,
    #     patient_id=patient.id,
    # )
    prescriptions = await get_patient_prescriptions(
        db=db,
        patient_id=patient.id,
    )

    all_medicine_names = {
        item.medicine_name
        for prescription in prescriptions
        for item in prescription.items
    }

    existing_medicines = (
        await get_existing_medicine_names(
            db,
            list(all_medicine_names),
        )
    )

    return [
        to_prescription_response(
            prescription,
            existing_medicines,
        )
        for prescription in prescriptions
    ]


@router.get(
    "/appointments/{appointment_id}",
    response_model=PrescriptionResponse,
)
async def appointment_prescription_endpoint(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(
        UserRole.DOCTOR,
        UserRole.PATIENT,
        UserRole.ADMIN,
    )),
):

    prescription = await get_appointment_prescription(
        db=db,
        appointment_id=appointment_id,
    )

    # if user.role == UserRole.DOCTOR:

    #     if not user.doctor:
    #         raise ForbiddenError("Doctor profile not found")

    #     if prescription.doctor_id != user.doctor.id:
    #         raise ForbiddenError("Not allowed")

    if user.role == UserRole.DOCTOR:

        doctor_profile = await get_doctor_profile(
            db=db,
            user_id=user.id,
        )

        if prescription.doctor_id != doctor_profile.id:
            raise ForbiddenError("Not allowed")

    elif user.role == UserRole.PATIENT:
        if prescription.patient_id != user.id:
            raise ForbiddenError("Not allowed")

    #return prescription

    medicine_names = [
        item.medicine_name
        for item in prescription.items
    ]

    existing_medicines = (
        await get_existing_medicine_names(
            db,
            medicine_names,
        )
    )

    return to_prescription_response(
        prescription,
        existing_medicines,
    )



@router.get("/{prescription_id}/pdf")
async def download_prescription_pdf(
    prescription_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(
        UserRole.DOCTOR,
        UserRole.PATIENT,
        UserRole.ADMIN,
    )),
):

    prescription = await get_prescription_by_id(
        db=db,
        prescription_id=prescription_id,
    )

    # ====================================
    # RBAC CHECK
    # ====================================

    # if user.role == UserRole.DOCTOR:

    #     if not user.doctor:
    #         raise ForbiddenError("Doctor profile not found")

    #     if prescription.doctor_id != user.doctor.id:
    #         raise ForbiddenError("Not allowed")


    if user.role == UserRole.DOCTOR:

        doctor_profile = await get_doctor_profile(
            db=db,
            user_id=user.id,
        )
        
        if prescription.doctor_id != doctor_profile.id:
            raise ForbiddenError("Not allowed")

    elif user.role == UserRole.PATIENT:
        
        if prescription.patient_id != user.id:
            raise ForbiddenError("Not allowed")
        


    if prescription.status != PrescriptionStatus.ISSUED:
        raise BadRequestError(
            "Prescription not issued yet"
        )

    # ====================================
    # GENERATE PDF
    # ====================================

    pdf = generate_prescription_pdf(
        prescription
    )

    filename = (
        f"prescription_{prescription.id}.pdf"
    )

    await log_audit_event(
        db=db,
        event_type="prescription",
        action="download_pdf",
        user_id=user.id,
        resource="prescription",
        details={
            "prescription_id": prescription.id,
        },
    )

    return StreamingResponse(
        BytesIO(pdf),
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f"attachment; filename={filename}"
        },
    )



@router.patch(
    "/{prescription_id}",
    response_model=PrescriptionResponse,
)
async def update_prescription_endpoint(
    prescription_id: int,
    data: PrescriptionUpdate,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(
        require_roles(UserRole.DOCTOR)
    ),
):

    prescription = await get_prescription_by_id(
        db=db,
        prescription_id=prescription_id,
    )

    # ====================================
    # OWNERSHIP CHECK
    # ====================================

    # if not doctor.doctor:
    #     raise ForbiddenError("Doctor profile not found")

    # if prescription.doctor_id != doctor.doctor.id:
    #     raise ForbiddenError("Not allowed")

    doctor_profile = await get_doctor_profile(
            db=db,
            user_id=doctor.id,
        )

    if prescription.doctor_id != doctor_profile.id:
        raise ForbiddenError("Not allowed")
    
    updated = await update_prescription(
        db=db,
        prescription=prescription,
        data=data,
    )

    await db.commit()

    await db.refresh(updated)

    #return updated

    medicine_names = [
        item.medicine_name
        for item in updated.items
    ]

    existing_medicines = (
        await get_existing_medicine_names(
            db,
            medicine_names,
        )
    )

    return to_prescription_response(
        updated,
        existing_medicines,
    )


@router.get(
    "/verify/{prescription_uuid}",
    response_model=PrescriptionVerificationResponse,
)
async def verify_prescription(
    prescription_uuid: UUID,
    db: AsyncSession = Depends(get_db),
):

    result = await verify_prescription_by_uuid(
        db=db,
        prescription_uuid=prescription_uuid,
    )

    return result