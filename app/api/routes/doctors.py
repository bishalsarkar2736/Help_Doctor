from fastapi import APIRouter, Depends,Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from app.db.postgres import get_db
from app.models.user import User
from app.models.doctor import Doctor, DoctorStatus
from app.domain.clinics.visibility import clinic_is_public
from app.models.clinic import Clinic
from app.security.rbac import require_roles
from app.models.user import UserRole
from app.try_except.exceptions import NotFoundError
from app.security.file_urls import sign_key

from fastapi import UploadFile
from fastapi import File

from app.services.doctor_service import (
    upload_doctor_signature,
)

from app.schemas.doctor_signature import (
    DoctorSignatureResponse,
)
from app.schemas.doctor_document import DoctorDocumentResponse
from app.models.doctor_document import DoctorDocumentType
from app.services.doctor_document_service import (
    upload_doctor_document,
    list_own_documents,
)

from app.schemas.doctor import (
    DoctorListItem,
    DoctorDetail,
    DoctorMe,
    DoctorProfileUpdate,
    DoctorProfileResponse,
    DoctorProfileCreate,
)

from app.services.doctor_service import (
    create_doctor_profile,
    update_doctor_profile,
)
from app.schemas.doctor_search import DoctorSearchOut
from app.services.doctor_search_service import search_doctors



router = APIRouter(prefix="/doctors", tags=["Doctors"])



@router.post(
    "/profile",
    response_model=DoctorProfileResponse,
)
async def create_profile(
    data: DoctorProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    return await create_doctor_profile(
        db=db,
        user=current_user,
        data=data,
    )


@router.get("", response_model=list[DoctorListItem])
async def list_doctors(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(
        default=None,
        description="Search by doctor name or specialization",
    ),
    specialization: str | None = Query(default=None),
    clinic_id: int | None = Query(default=None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    # Select COLUMNS, not ORM entities.
    #
    # `select(Doctor, User, Clinic)` returns mapped instances, and Doctor, User
    # and Clinic each declare relationships with lazy="selectin" — which load
    # eagerly on every fetch and cascade into one another
    # (Doctor -> Clinic -> every doctor/appointment/prescription/payment/admin
    # in that clinic). Loading a single doctor that way emitted 41 SQL
    # statements and cost ~90ms, and the cost scaled with clinic size rather
    # than with the page of results.
    #
    # This endpoint only ever reads the nine scalars below, so selecting them
    # directly avoids entity hydration altogether: one statement, no eager
    # loading, and no change to any model — nothing outside this query is
    # affected.
    query = (
        select(
            Doctor.id.label("doctor_id"),
            Doctor.specialization,
            Doctor.experience_years,
            Doctor.bio,
            Doctor.consultation_fee,
            Doctor.clinic_id,
            User.full_name,
            User.email,
            Clinic.name.label("clinic_name"),
        )
        .join(User, Doctor.user_id == User.id)
        # INNER join now, not outer. A doctor with no clinic, or one whose
        # clinic is suspended or deleted, is not publicly listable — the outer
        # join kept both in the directory.
        .join(Clinic, Doctor.clinic_id == Clinic.id)
        .where(
            Doctor.status == DoctorStatus.APPROVED,
            User.is_active.is_(True),
            *clinic_is_public(),
        )
    )

    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                User.full_name.ilike(pattern),
                Doctor.specialization.ilike(pattern),
            )
        )

    if specialization:
        query = query.where(
            func.lower(Doctor.specialization) == specialization.strip().lower()
        )

    if clinic_id is not None:
        query = query.where(Doctor.clinic_id == clinic_id)

    query = query.order_by(User.full_name).limit(limit).offset(offset)

    rows = (await db.execute(query)).all()

    return [
        DoctorListItem(
            id=row.doctor_id,
            name=row.full_name,
            email=row.email,
            specialization=row.specialization,
            experience_years=row.experience_years,
            bio=row.bio,
            consultation_fee=row.consultation_fee,
            clinic_id=row.clinic_id,
            # outerjoin: NULL when the doctor is not attached to a clinic.
            clinic_name=row.clinic_name,
        )
        for row in rows
    ]


@router.patch("/profile")
async def update_profile(
    data: DoctorProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.DOCTOR)
    ),
):
    return await update_doctor_profile(
        db=db,
        current_user=current_user,
        data=data,
    )


@router.post(
    "/signature",
    response_model=DoctorSignatureResponse,
)
async def upload_signature(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.DOCTOR)
    ),
):
    doctor = await upload_doctor_signature(
        db=db,
        current_user=current_user,
        file=file,
    )

    # Signed, not the bare key: media/signatures/ is no longer public, so the
    # bare key would render as a broken image. The stored column keeps the key.
    return DoctorSignatureResponse(
        signature_file_path=sign_key(
            doctor.signature_file_path,
            access_version=doctor.signature_access_version,
        ),
        signature_uploaded_at=doctor.signature_uploaded_at,
    )



@router.get(
    "/search",
    response_model=list[DoctorSearchOut],
)
async def search_doctors_endpoint(
    q: str = Query(
        ...,
        min_length=1,
        description="Search doctors by name, email or specialization",
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
    return await search_doctors(
        db=db,
        q=q,
        limit=limit,
        offset=offset,
    )


# ---- The signed-in doctor's OWN profile + status ----
# NOTE: declared BEFORE the dynamic "/{doctor_id}" route so it isn't shadowed.
# Returns the record regardless of approval status; 404 only if no profile
# exists yet (so the frontend can show the "complete your profile" form).
@router.get("/me", response_model=DoctorMe)
async def get_my_doctor_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    # Columns, not entities — this runs on every doctor screen load and cost
    # ~90-125ms because selecting Doctor and Clinic dragged in their
    # lazy="selectin" relationships and cascaded across the clinic.
    result = await db.execute(
        select(
            Doctor.id.label("doctor_id"),
            Doctor.user_id,
            Doctor.specialization,
            Doctor.experience_years,
            Doctor.bio,
            Doctor.qualification,
            Doctor.medical_registration_number,
            Doctor.consultation_fee,
            Doctor.status,
            Doctor.rejection_reason,
            Doctor.clinic_id,
            Doctor.signature_file_path,
            Doctor.signature_uploaded_at,
            # Not exposed in DoctorMe — it exists only to sign the URL below.
            Doctor.signature_access_version,
            Doctor.created_at,
            Clinic.name.label("clinic_name"),
        )
        .outerjoin(Clinic, Doctor.clinic_id == Clinic.id)
        .where(Doctor.user_id == current_user.id)
    )
    row = result.first()

    if row is None:
        raise NotFoundError("Doctor profile not found")

    return DoctorMe(
        id=row.doctor_id,
        user_id=row.user_id,
        specialization=row.specialization,
        experience_years=row.experience_years,
        bio=row.bio,
        qualification=row.qualification,
        medical_registration_number=row.medical_registration_number,
        consultation_fee=row.consultation_fee,
        status=row.status,
        rejection_reason=row.rejection_reason,
        clinic_id=row.clinic_id,
        # outerjoin: NULL when the doctor is not attached to a clinic.
        clinic_name=row.clinic_name,
        # The doctor's own credentials page renders this in an <img>, which
        # cannot send an Authorization header — so the capability travels in
        # the URL. None stays None: there is nothing to sign.
        signature_file_path=(
            sign_key(
                row.signature_file_path,
                access_version=row.signature_access_version,
            )
            if row.signature_file_path
            else None
        ),
        signature_uploaded_at=row.signature_uploaded_at,
        created_at=row.created_at,
    )


# ---- Public: distinct specializations (for the Find Doctors filter) ----
# NOTE: declared BEFORE the dynamic "/{doctor_id}" route so it isn't shadowed.
@router.get("/specializations", response_model=list[str])
async def list_specializations(
    db: AsyncSession = Depends(get_db),
    clinic_id: int | None = Query(
        default=None,
        description="Restrict to specializations this clinic actually offers",
    ),
):
    """Specializations a patient can actually be seen for.

    clinic_id is optional rather than required because this backs the public
    Find Doctors page, which deliberately browses every clinic and has an
    "All clinics" option that the platform-wide list fills.

    When a clinic IS chosen the list narrows with it. Without that the filter
    offered specializations the selected clinic does not practise, and picking
    one returned no doctors — the page looked broken while answering honestly.
    """
    statement = (
        select(Doctor.specialization)
        .join(User, Doctor.user_id == User.id)
        .join(Clinic, Doctor.clinic_id == Clinic.id)
        .where(
            Doctor.status == DoctorStatus.APPROVED,
            User.is_active.is_(True),
            *clinic_is_public(),
        )
        .distinct()
        .order_by(Doctor.specialization)
    )

    if clinic_id is not None:
        statement = statement.where(Doctor.clinic_id == clinic_id)

    result = await db.execute(statement)

    return [row[0] for row in result.all()]


# ---------------- Credential documents ----------------
# Uploaded by the doctor while PENDING; reviewed by a clinic admin before
# approval. MUST be declared BEFORE the dynamic "/{doctor_id}" route —
# FastAPI matches in declaration order, so /{doctor_id} would otherwise
# swallow "documents" and fail with 422.

@router.post(
    "/documents",
    response_model=DoctorDocumentResponse,
    status_code=201,
)
async def upload_credential_document(
    doc_type: DoctorDocumentType,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    return await upload_doctor_document(
        db=db,
        user=current_user,
        doc_type=doc_type,
        file=file,
    )


@router.get(
    "/documents",
    response_model=list[DoctorDocumentResponse],
)
async def list_my_credential_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    return await list_own_documents(db=db, user=current_user)


# ---- Public: single doctor detail (approved + active only) ----
@router.get("/{doctor_id}", response_model=DoctorDetail)
async def get_doctor_detail(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
):
    # Columns, not entities — same reason as the list endpoint above: selecting
    # Doctor/User/Clinic as mapped objects drags in their lazy="selectin"
    # relationships and cascades across the whole clinic. Measured at 136ms for
    # a single doctor.
    result = await db.execute(
        select(
            Doctor.id.label("doctor_id"),
            Doctor.specialization,
            Doctor.experience_years,
            Doctor.bio,
            Doctor.qualification,
            Doctor.consultation_fee,
            Doctor.clinic_id,
            User.full_name,
            User.email,
            Clinic.name.label("clinic_name"),
        )
        .join(User, Doctor.user_id == User.id)
        .join(Clinic, Doctor.clinic_id == Clinic.id)
        .where(
            Doctor.id == doctor_id,
            Doctor.status == DoctorStatus.APPROVED,
            User.is_active.is_(True),
            *clinic_is_public(),
        )
    )
    row = result.first()

    if row is None:
        raise NotFoundError("Doctor not found")

    return DoctorDetail(
        id=row.doctor_id,
        name=row.full_name,
        email=row.email,
        specialization=row.specialization,
        experience_years=row.experience_years,
        bio=row.bio,
        qualification=row.qualification,
        consultation_fee=row.consultation_fee,
        clinic_id=row.clinic_id,
        # outerjoin: NULL when the doctor is not attached to a clinic.
        clinic_name=row.clinic_name,
    )
