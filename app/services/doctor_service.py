from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.domain.policies.doctor_policy import DoctorPolicy

from datetime import datetime

from fastapi import UploadFile

from app.core.time import UTC


from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User
from app.try_except.exceptions import BadRequestError,NotFoundError
from app.security.file_validation import ensure_image
from app.services.storage import get_storage

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


# verify_doctor was removed here. It approved a doctor selected by primary key
# alone, behind a role-only check, so any clinic's admin could have approved
# any clinic's doctor. Nothing called it: no route, no service, no test.
#
# It was also a second implementation of work that already exists.
# admin_doctor_service.approve_doctor resolves the acting admin's clinic,
# assigns the doctor to it, and is the function POST /admin/doctors/{id}/approve
# actually reaches. Scoping this one would have left two approval paths, one of
# them the wrong one to pick up.


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

    # Key, not a path — see app/services/storage.py. Same string the old code
    # stored, so existing rows stay valid.
    key = f"media/signatures/doctor_{doctor.id}{extension}"

    get_storage().write(key, content)

    doctor.signature_file_path = key

    doctor.signature_uploaded_at = (
        datetime.now(UTC)
    )

    # Revoke every signed URL minted for the previous signature.
    #
    # This is the only operation that replaces a signature, so it is the only
    # place the version needs to move. Without it, a URL handed out for the old
    # image keeps working against the new one: the key is unchanged when the
    # extension matches (doctor_7.png overwritten in place), so an old link
    # would silently start serving the replacement.
    #
    # Incremented unconditionally, including the first upload where there is
    # nothing to revoke. Branching on "was there a signature before" would add a
    # way to get this wrong for no gain — a bump with no outstanding URLs costs
    # nothing.
    #
    # Written as a SQL expression, not doctor.signature_access_version + 1, so
    # two concurrent uploads by the same doctor cannot both read 3 and both
    # write 4. The refresh below reloads whatever the database settled on.
    doctor.signature_access_version = Doctor.signature_access_version + 1

    await db.flush()

    await db.refresh(doctor)

    return doctor