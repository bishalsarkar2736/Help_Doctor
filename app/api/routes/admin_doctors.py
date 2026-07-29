from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.postgres import get_db
from app.security.rbac import require_roles
from app.models.user import User, UserRole
from app.models.doctor import Doctor

from pathlib import Path

from fastapi.responses import FileResponse

from app.schemas.admin_doctor import AdminDoctorListItem, DoctorRejectRequest
from app.schemas.doctor_document import DoctorDocumentResponse
from app.services.doctor_document_service import list_documents_for_admin
from app.try_except.exceptions import NotFoundError
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
    result = await db.execute(
        select(Doctor, User)
        .join(User, Doctor.user_id == User.id)
        .limit(limit)
        .offset(offset)
    )

    rows = result.all()

    return [
        AdminDoctorListItem(
            id=doctor.id,
            name=user.full_name,
            email=user.email,
            specialization=doctor.specialization,
            experience_years=doctor.experience_years,
            bio=doctor.bio,
            status=doctor.status,
            is_active=user.is_active,
            approved_at=doctor.approved_at,
            rejected_at=doctor.rejected_at,
            rejection_reason=doctor.rejection_reason,
        )
        for doctor, user in rows
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

    path = Path(document.file_path)
    if not path.is_file():
        raise NotFoundError("Stored file is missing")

    return FileResponse(
        path,
        media_type=document.content_type or "application/octet-stream",
        filename=document.original_filename or path.name,
    )
