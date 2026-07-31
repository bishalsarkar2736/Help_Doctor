from fastapi import APIRouter, Depends,Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from app.db.postgres import get_db
from app.schemas.prescription import (
    PrescriptionCreate,
    PrescriptionResponse,
)
from app.security.rbac import require_roles
from app.models.phi_access_log import PHIAction, PHIResourceType
from app.services.phi_access_log_service import log_phi_access
from app.models.user import User, UserRole
from app.try_except.exceptions import NotFoundError, ForbiddenError,BadRequestError
from app.models.prescription import Prescription,PrescriptionStatus
from app.services.prescription_service import (
    create_prescription,
    issue_prescription,
    get_active_draft_revision,
    get_prescription_by_id,
    get_patient_prescriptions,
    get_appointment_prescription,
    update_prescription,
    get_doctor_prescriptions,
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
    PrescriptionRevisionHistoryResponse,
    PrescriptionSearchOut
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
from app.services.clinic_service import (
    get_clinic_by_id,
)
from app.services.prescription_search_service import (
    search_prescriptions,
)
from app.services.tenant_resolver import (
    resolve_clinic_id,
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
    
    doctor_profile = await get_doctor_profile(
        db=db,
        user_id=doctor.id,
    )

    result = await db.execute(
        select(Prescription)
        .where(
            Prescription.id == prescription_id,
            Prescription.doctor_id == doctor_profile.id,
            Prescription.clinic_id == doctor_profile.clinic_id,
        )
    )

    prescription = result.scalar_one_or_none()

    if not prescription:
        raise NotFoundError(
            "Prescription not found"
        )

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
    "/{prescription_id}/revisions/issue",
)
async def issue_draft_revision_endpoint(
    prescription_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    result = await db.execute(
        select(Doctor).where(Doctor.user_id == current_user.id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise ForbiddenError("Doctor profile not found")

    prescription = await get_prescription_by_id(
        db=db,
        prescription_id=prescription_id,
        user=current_user,
    )

    if prescription.doctor_id != doctor.id:
        raise ForbiddenError("Not allowed")

    revision = await get_active_draft_revision(
        db=db,
        prescription=prescription,
    )

    await issue_prescription(
        db=db,
        prescription=revision,
        transition_appointment=False,
    )

    await db.commit()

    return {
        "message": "prescription_revision_issued"
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
        user=current_user,
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
    "/search",
    response_model=list[PrescriptionSearchOut],
)
async def search_prescriptions_endpoint(
    clinic_id: int,
    patient: str | None = Query(default=None),
    doctor: str | None = Query(default=None),
    medication: str | None = Query(default=None),
    status: PrescriptionStatus | None = Query(default=None),
    issue_date: date | None = Query(default=None),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.RECEPTIONIST,
        )
    ),
):
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=current_user,
        clinic_id=clinic_id,
    )

    return await search_prescriptions(
        db=db,
        clinic_id=resolved_clinic_id,
        patient=patient,
        doctor=doctor,
        medication=medication,
        status=status,
        issue_date=issue_date,
        limit=limit,
        offset=offset,
    )
    

@router.get(
    "/{prescription_id}/revisions/history",
    response_model=PrescriptionRevisionHistoryResponse,
)
async def get_revision_history(
    prescription_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    
    prescription = await get_prescription_by_id(
        db=db,
        prescription_id=prescription_id,
        user=current_user,
    )

    doctor = await get_doctor_profile(
        db=db,
        user_id=current_user.id,
    )

    if prescription.doctor_id != doctor.id:
        raise ForbiddenError("Not allowed")
    

    revisions = await get_prescription_revision_history(
        db=db,
        prescription_id=prescription_id,
        clinic_id=prescription.clinic_id,
    )

    return {
        "items": revisions
    }



# NOTE: static "/me" MUST be declared before the dynamic "/{prescription_id}"
# route, otherwise "me" is matched as a prescription id (→ 422).
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
        user=user,
    )

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

    # A prescription names the patient and every medicine they were given.
    await log_phi_access(
        db=db,
        actor=user,
        patient_id=prescription.patient_id,
        resource_type=PHIResourceType.PRESCRIPTION,
        resource_id=prescription.id,
        action=PHIAction.VIEW,
        clinic_id=prescription.clinic_id,
    )

    return to_prescription_response(
        prescription,
        existing_medicines,
    )


@router.get(
    "/doctor/me",
    response_model=list[PrescriptionResponse],
)
async def my_created_prescriptions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_roles(UserRole.DOCTOR)
    ),
):
    doctor = await get_doctor_profile(
        db=db,
        user_id=user.id,
    )

    prescriptions = await get_doctor_prescriptions(
        db=db,
        doctor=doctor,
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
        user=user,
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
        user=user,
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

        if not doctor_profile:
            raise ForbiddenError(
                "Doctor profile not found"
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

    clinic = await get_clinic_by_id(
        db,
        prescription.clinic_id,
    )

    if not clinic:
        raise NotFoundError(
            "Clinic not found"
        )
    

    pdf = generate_prescription_pdf(
        prescription=prescription,
        clinic=clinic,
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

    # Also recorded as a PHI access. The audit entry above tracks the action
    # for the prescription; this one answers "who obtained this patient's
    # data", which is the question asked of an access log — and a downloaded
    # PDF leaves the system entirely, so it is the disclosure that matters most.
    await log_phi_access(
        db=db,
        actor=user,
        patient_id=prescription.patient_id,
        resource_type=PHIResourceType.PRESCRIPTION_PDF,
        resource_id=prescription.id,
        action=PHIAction.DOWNLOAD,
        clinic_id=prescription.clinic_id,
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
        user=doctor,
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