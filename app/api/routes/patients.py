from fastapi import APIRouter, Depends, Query, Request
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
from app.core.limiter import authenticated_key, limiter
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



async def _searcher_clinic_id(db: AsyncSession, user: User) -> int:
    """The clinic whose patients this caller may search.

    Taken from the authenticated principal, never from the request.
    resolve_clinic_id returns the CALLER-SUPPLIED value unchanged for
    receptionists, so scoping to it would let the search be pointed at another
    tenant by editing a query string — defeating the filter this exists to
    enforce.
    """
    if user.role == UserRole.DOCTOR:
        doctor = await db.scalar(
            select(Doctor.clinic_id).where(Doctor.user_id == user.id)
        )

        if doctor is None:
            raise ForbiddenError("Doctor is not assigned to a clinic")

        return doctor

    # Admins and receptionists carry their clinic on the user record.
    if user.clinic_id is None:
        raise ForbiddenError("User is not assigned to a clinic")

    return user.clinic_id


@router.get(
    "/search",
    response_model=list[PatientSearchOut],
)
# Per authenticated user, not per address — see authenticated_key. A clinic
# shares one office connection, so an IP limit would have the front desk
# throttling itself while a stolen token used elsewhere got a clean budget.
#
# 60/minute is far above what a person at a desk produces and far below what
# a script wants. It does not stop a receptionist reading their own clinic's
# roster, which they are entitled to do and which the clinic scoping already
# bounds; it makes bulk extraction slow and noisy, and every surfaced patient
# is already written to the PHI log.
#
# The number is only safe because the frontend debounces. Search runs on every
# keystroke, so an undebounced 13-character name was 12 requests — and 12
# PHI-log writes per matched patient. That is a rate limit's worst enemy: real
# users hitting it during ordinary work.
@limiter.limit("60/minute", key_func=authenticated_key)
async def search_patient_endpoint(
    request: Request,
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
    clinic_id = await _searcher_clinic_id(db, current_user)

    results = await search_patients(
        db=db,
        clinic_id=clinic_id,
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
