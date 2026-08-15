from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select

from app.db.postgres import get_db
from app.security.rbac import require_roles
from app.models.user import User, UserRole
from app.models.doctor import Doctor

from pathlib import Path

from fastapi import Response
from fastapi.responses import FileResponse

from app.services.storage import get_storage

from app.schemas.admin_doctor import AdminDoctorListItem, DoctorRejectRequest
from app.schemas.doctor_document import DoctorDocumentResponse
from app.services.doctor_document_service import list_documents_for_admin
from app.try_except.exceptions import ForbiddenError, NotFoundError
from app.services.tenant_resolver import resolve_clinic_id
from app.services.admin_doctor_service import (
    approve_doctor,
    reject_doctor,
    suspend_doctor,
    reinstate_doctor,
)

router = APIRouter(
    prefix="/admin/doctors",
    tags=["Admin - Doctors"],
)


# ✅ List all doctors (ADMIN ONLY)
@router.get("", response_model=list[AdminDoctorListItem])
async def admin_list_doctors(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    # Their own clinic's doctors, plus applicants nobody has accepted yet.
    #
    # This query had no WHERE clause at all, so any clinic admin could page
    # through every doctor on the platform — including other clinics' staff
    # emails and the rejection_reason a rival admin had written. It was also
    # the enumeration aid for the approval-capture defect.
    #
    # clinic_id IS NULL stays visible on purpose: a doctor applies before any
    # clinic has accepted them, and this list is how an admin finds someone to
    # approve. It is the same rule list_documents_for_admin and approve_doctor
    # apply — mine, or nobody's yet.
    #
    # Fails closed on an admin with no clinic rather than degrading to the
    # platform-wide listing this is removing.
    if not admin.clinic_id:
        raise ForbiddenError("Admin not assigned to clinic")

    # Columns, not entities — Doctor and User both declare lazy="selectin"
    # relationships that cascade across the clinic on every row fetched.
    result = await db.execute(
        select(
            Doctor.id.label("doctor_id"),
            Doctor.specialization,
            Doctor.experience_years,
            Doctor.bio,
            Doctor.status,
            Doctor.approved_at,
            Doctor.rejected_at,
            Doctor.rejection_reason,
            User.full_name,
            User.email,
            User.is_active,
        )
        .join(User, Doctor.user_id == User.id)
        .where(
            or_(
                Doctor.clinic_id.is_(None),
                Doctor.clinic_id == admin.clinic_id,
            )
        )
        .limit(limit)
        .offset(offset)
    )

    rows = result.all()

    return [
        AdminDoctorListItem(
            id=row.doctor_id,
            name=row.full_name,
            email=row.email,
            specialization=row.specialization,
            experience_years=row.experience_years,
            bio=row.bio,
            status=row.status,
            is_active=row.is_active,
            approved_at=row.approved_at,
            rejected_at=row.rejected_at,
            rejection_reason=row.rejection_reason,
        )
        for row in rows
    ]


# ✅ Approve doctor (verification) — assigns the admin's clinic
@router.post("/{doctor_id}/approve")
async def approve(
    doctor_id: int,
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await approve_doctor(
        db=db,
        admin=admin,
        clinic_id=resolved_clinic_id,
        doctor_id=doctor_id,
    )


# ✅ Reject doctor application
@router.post("/{doctor_id}/reject")
async def reject(
    doctor_id: int,
    body: DoctorRejectRequest | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return await reject_doctor(
        db=db,
        admin=admin,
        doctor_id=doctor_id,
        reason=body.reason if body else None,
    )


# ✅ Suspend an approved doctor
@router.post("/{doctor_id}/suspend")
async def suspend(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return await suspend_doctor(
        db=db,
        admin=admin,
        doctor_id=doctor_id,
    )


# ✅ Reinstate a suspended doctor
@router.post("/{doctor_id}/reinstate")
async def reinstate(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return await reinstate_doctor(
        db=db,
        admin=admin,
        doctor_id=doctor_id,
    )


# ---------------- Credential review ----------------

@router.get(
    "/{doctor_id}/documents",
    response_model=list[DoctorDocumentResponse],
)
async def list_doctor_documents(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Credential documents for an applicant, scoped to the admin's clinic."""
    return await list_documents_for_admin(
        db=db,
        admin=admin,
        doctor_id=doctor_id,
    )


@router.get("/{doctor_id}/documents/{document_id}/file")
async def download_doctor_document(
    doctor_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Stream the actual file so the admin can review it before approving."""
    documents = await list_documents_for_admin(
        db=db, admin=admin, doctor_id=doctor_id
    )

    document = next((d for d in documents if d.id == document_id), None)
    if document is None:
        raise NotFoundError("Document not found")

    storage = get_storage()
    if not storage.exists(document.file_path):
        raise NotFoundError("Stored file is missing")

    filename = (
        document.original_filename or Path(document.file_path).name
    )
    media_type = document.content_type or "application/octet-stream"

    # FileResponse streams from disk without buffering the whole file, so it
    # stays the better option while storage is local. A backend with no local
    # path (S3/MinIO) returns None and we fall back to streaming the bytes.
    path = storage.local_path(document.file_path)
    if path is not None:
        return FileResponse(path, media_type=media_type, filename=filename)

    return Response(
        content=storage.read(document.file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
