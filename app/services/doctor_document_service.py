"""Doctor credential documents (BMDC certificate, degree, licence).

Uploaded by the doctor while PENDING, reviewed by a clinic admin before
approval. Content type is verified by magic bytes — never by the client-supplied
header.
"""

import logging
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_document import DoctorDocument, DoctorDocumentType
from app.models.user import User, UserRole
from app.services.storage import get_storage
from app.security.file_validation import ensure_document
from app.try_except.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# Key prefix, not a directory — see app/services/storage.py.
UPLOAD_PREFIX = "uploads/doctor_documents"
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024  # 5 MB

ALLOWED_DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


async def _get_own_doctor(db: AsyncSession, user: User) -> Doctor:
    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Only doctors can manage credential documents")

    doctor = await db.scalar(
        select(Doctor).where(Doctor.user_id == user.id)
    )
    if doctor is None:
        raise NotFoundError("Doctor profile not found")
    return doctor


async def upload_doctor_document(
    *,
    db: AsyncSession,
    user: User,
    doc_type: DoctorDocumentType,
    file: UploadFile,
) -> DoctorDocument:
    doctor = await _get_own_doctor(db, user)

    content = await file.read()

    if not content:
        raise BadRequestError("File is empty")

    if len(content) > MAX_DOCUMENT_BYTES:
        raise BadRequestError("File too large (max 5MB)")

    # Never trust file.content_type — verify the actual bytes.
    try:
        detected = ensure_document(content, set(ALLOWED_DOCUMENT_TYPES))
    except ValueError:
        raise BadRequestError(
            "Only PDF, PNG, JPEG or WEBP files are allowed"
        )

    storage = get_storage()

    extension = ALLOWED_DOCUMENT_TYPES[detected]
    key = (
        f"{UPLOAD_PREFIX}/"
        f"doctor{doctor.id}_{doc_type.value}_{uuid4().hex}{extension}"
    )
    storage.write(key, content)

    # One document per type: replace the previous one so review stays simple.
    existing = await db.scalars(
        select(DoctorDocument).where(
            DoctorDocument.doctor_id == doctor.id,
            DoctorDocument.doc_type == doc_type,
        )
    )
    for old in existing:
        storage.delete(old.file_path)
        await db.delete(old)

    document = DoctorDocument(
        doctor_id=doctor.id,
        doc_type=doc_type,
        file_path=key,
        original_filename=file.filename,
        content_type=detected,
        size_bytes=len(content),
    )
    db.add(document)

    # Re-uploading after a rejection puts the doctor back in the review queue,
    # otherwise REJECTED would be a dead end with no way to re-apply.
    if doctor.status == DoctorStatus.REJECTED:
        doctor.status = DoctorStatus.PENDING
        doctor.rejection_reason = None

    await db.flush()
    await db.refresh(document)

    return document


async def list_own_documents(
    *,
    db: AsyncSession,
    user: User,
) -> list[DoctorDocument]:
    doctor = await _get_own_doctor(db, user)

    result = await db.scalars(
        select(DoctorDocument)
        .where(DoctorDocument.doctor_id == doctor.id)
        .order_by(DoctorDocument.uploaded_at.desc())
    )
    return list(result)


async def list_documents_for_admin(
    *,
    db: AsyncSession,
    admin: User,
    doctor_id: int,
) -> list[DoctorDocument]:
    """Clinic admin reviewing an applicant — scoped to their own clinic."""
    doctor = await db.get(Doctor, doctor_id)

    if doctor is None:
        raise NotFoundError("Doctor not found")

    if doctor.clinic_id is not None and doctor.clinic_id != admin.clinic_id:
        raise ForbiddenError("Doctor belongs to another clinic")

    result = await db.scalars(
        select(DoctorDocument)
        .where(DoctorDocument.doctor_id == doctor_id)
        .order_by(DoctorDocument.uploaded_at.desc())
    )
    return list(result)
