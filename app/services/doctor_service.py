from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.domain.policies.doctor_policy import DoctorPolicy

from pathlib import Path
from datetime import datetime

from fastapi import UploadFile

from app.core.time import UTC


from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User
from app.try_except.exceptions import BadRequestError,NotFoundError
from app.security.file_validation import ensure_image

from app.schemas.doctor import (
    DoctorProfileUpdate,
    DoctorProfileCreate,
)


async def create_doctor_profile(
    db: AsyncSession,
    user: User,
    data: DoctorProfileCreate,
) -> Doctor:
    
    DoctorPolicy.can_create_profile(user)


    result = await db.execute(
        select(Doctor).where(Doctor.user_id == user.id)
    )
    if result.scalar_one_or_none():
        raise BadRequestError("Doctor profile already exists")


    doctor = Doctor(
        user_id=user.id,
        specialization=data.specialization,
        experience_years=data.experience_years,
        bio=data.bio,
        # Invited doctors already carry their clinic (from accepting the
        # invite); self-applying doctors have it assigned at approval time.
        clinic_id=user.clinic_id,
        status=DoctorStatus.PENDING,
    )

    db.add(doctor)
    await db.flush()
    await db.refresh(doctor)

    return doctor


async def verify_doctor(
    db: AsyncSession,
    doctor_id: int,
    current_user : User
):
    
    DoctorPolicy.can_verify(current_user)

    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise NotFoundError("Doctor not found")

    doctor.status = DoctorStatus.APPROVED
    await db.flush()
    await db.refresh(doctor)

    return doctor


async def update_doctor_profile(
    *,
    db:AsyncSession,
    current_user: User,
    data: DoctorProfileUpdate,
):
    result = await db.execute(
        select(Doctor)
        .where(
            Doctor.user_id == current_user.id
        )
    )

    doctor = result.scalar_one_or_none()

    if not doctor:
        raise NotFoundError(
            "Doctor profile not found"
        )

    if data.medical_registration_number:

        existing = await db.execute(
            select(Doctor)
            .where(
                Doctor.medical_registration_number
                == data.medical_registration_number,
                Doctor.id != doctor.id,
            )
        )

        if existing.scalar_one_or_none():
            raise BadRequestError(
                "Registration number already exists"
            )

    if data.qualification is not None:
        doctor.qualification = data.qualification

    if data.medical_registration_number is not None:
        doctor.medical_registration_number = (
            data.medical_registration_number
        )

    if data.consultation_fee is not None:
        doctor.consultation_fee = (
            data.consultation_fee
        )

    await db.flush()

    await db.refresh(doctor)

    return doctor


async def upload_doctor_signature(
    *,
    db: AsyncSession,
    current_user: User,
    file: UploadFile,
):
    result = await db.execute(
        select(Doctor)
        .where(
            Doctor.user_id == current_user.id
        )
    )

    doctor = result.scalar_one_or_none()

    if not doctor:
        raise NotFoundError(
            "Doctor profile not found"
        )

    if not file.content_type:
        raise BadRequestError(
            "Invalid file"
        )

    allowed_types = {
        "image/png",
        "image/jpeg",
    }

    if file.content_type not in allowed_types:
        raise BadRequestError(
            "Only PNG or JPEG allowed"
        )

    content = await file.read()

    if len(content) > 2 * 1024 * 1024:
        raise BadRequestError(
            "File too large"
        )

    # Never trust the client's Content-Type — verify by magic bytes.
    try:
        detected = ensure_image(content, allowed_types)
    except ValueError:
        raise BadRequestError("Only PNG or JPEG images are allowed")

    extension = ".jpg" if detected == "image/jpeg" else ".png"

    signature_dir = Path(
        "media/signatures"
    )

    signature_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    filepath = signature_dir / f"doctor_{doctor.id}{extension}"

    filepath.write_bytes(content)

    doctor.signature_file_path = (
        str(filepath)
    )

    doctor.signature_uploaded_at = (
        datetime.now(UTC)
    )

    await db.flush()

    await db.refresh(doctor)

    return doctor