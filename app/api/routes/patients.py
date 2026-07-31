from fastapi import APIRouter, Depends,Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.postgres import get_db
from app.models.user import UserRole,User
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.models.appointment import Appointment
from app.security.rbac import require_roles
from app.schemas.patient import PatientCreate,PatientRead,PatientUpdate
from app.services.patient_service import (
    create_patient,
    get_my_patient,
    update_my_patient,
)
from app.services.patient_search_service import search_patients
from app.models.phi_access_log import PHIAction, PHIResourceType
from app.services.phi_access_log_service import (
    log_phi_access,
    log_phi_access_many,
)
from app.schemas.patient_search import PatientSearchOut
from app.try_except.exceptions import NotFoundError, ForbiddenError



router = APIRouter(prefix="/patients", tags=["patients"])



@router.post('/', response_model=PatientRead)
async def create_my_patient_profile(
    patient_in:PatientCreate,
    current_user = Depends(require_roles(UserRole.PATIENT)),
    db:AsyncSession = Depends(get_db),
):
    return await create_patient(
        db = db,
        user_id = current_user.id,
        patient_in = patient_in,
    )


@router.get("/me", response_model=PatientRead)
async def get_my_profile(
    current_user: User = Depends(require_roles(UserRole.PATIENT)),
    db: AsyncSession = Depends(get_db),
):
    return await get_my_patient(db=db, user_id=current_user.id)


@router.patch("/me", response_model=PatientRead)
async def update_my_profile(
    patient_in: PatientUpdate,
    current_user: User = Depends(require_roles(UserRole.PATIENT)),
    db: AsyncSession = Depends(get_db),
):
    return await update_my_patient(
        db=db,
        user_id=current_user.id,
        patient_in=patient_in,
    )


@router.get("/records")
def medical_records(
    current_user = Depends(require_roles(UserRole.ADMIN, UserRole.DOCTOR))
):
    return {"message" : "Doctor/Admin access"}



@router.get(
    "/search",
    response_model=list[PatientSearchOut],
)
async def search_patient_endpoint(
    q: str = Query(
        ...,
        min_length=1,
        description="Search by patient name, email or phone",
    ),
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
    results = await search_patients(
        db=db,
        q=q,
        limit=limit,
        offset=offset,
    )

    # Search surfaces identifying details (name, email, phone) for people the
    # searcher may have no relationship with, so each surfaced patient is
    # recorded. This is the query that reveals someone trawling the roster.
    await log_phi_access_many(
        db=db,
        actor=current_user,
        patient_ids=[r.user_id for r in results],
        resource_type=PHIResourceType.PATIENT_SEARCH,
        action=PHIAction.SEARCH,
    )

    return results

# Staff-facing patient record read — access-logged (PHI). Declared last so it
# never shadows the static /me, /records, /search routes above.
@router.get("/{patient_user_id}", response_model=PatientRead)
async def get_patient_record(
    patient_user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.RECEPTIONIST,
        )
    ),
):
    patient = await db.scalar(
        select(Patient).where(Patient.user_id == patient_user_id)
    )
    if patient is None:
        raise NotFoundError("Patient not found")

    # A doctor may only view patients they have a treatment relationship with
    # (an appointment). Admin/receptionist manage the clinic more broadly.
    clinic_id = current_user.clinic_id
    if current_user.role == UserRole.DOCTOR:
        doctor = await db.scalar(
            select(Doctor).where(Doctor.user_id == current_user.id)
        )
        has_relationship = doctor is not None and await db.scalar(
            select(Appointment.id)
            .where(
                Appointment.doctor_id == doctor.id,
                Appointment.patient_id == patient_user_id,
            )
            .limit(1)
        )
        if not has_relationship:
            raise ForbiddenError("No treatment relationship with this patient")
        clinic_id = doctor.clinic_id

    # PatientRead exposes allergies, current medications, chronic conditions and
    # blood type — this read is a PHI disclosure and must leave a trace.
    await log_phi_access(
        db=db,
        actor=current_user,
        patient_id=patient_user_id,
        resource_type=PHIResourceType.PATIENT_PROFILE,
        resource_id=patient.id,
        action=PHIAction.VIEW,
        clinic_id=clinic_id,
    )
    return patient
