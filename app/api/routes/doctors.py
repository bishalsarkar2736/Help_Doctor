from fastapi import APIRouter, Depends,Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.postgres import get_db
from app.models.user import User
from app.models.doctor import Doctor
from app.security.rbac import require_roles
from app.models.user import UserRole

from fastapi import UploadFile
from fastapi import File

from app.services.doctor_service import (
    upload_doctor_signature,
)

from app.schemas.doctor_signature import (
    DoctorSignatureResponse,
)

from app.schemas.doctor import (
    DoctorListItem,
    DoctorProfileUpdate,
)

from app.services.doctor_service import (
    create_doctor_profile,
    update_doctor_profile,
)


router = APIRouter(prefix="/doctors", tags=["Doctors"])



@router.post("/profile")
async def create_profile(
    specialization: str,
    experience_years: int,
    bio: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.DOCTOR)),
):
    return await create_doctor_profile(
        db,
        current_user,
        specialization,
        experience_years,
        bio,
    )


@router.get("", response_model=list[DoctorListItem])
async def list_doctors(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    result = await db.execute(
        select(Doctor, User)
        .join(User, Doctor.user_id == User.id)
        .where(
            Doctor.is_verified.is_(True),
            User.is_active.is_(True),
        )
        .limit(limit)
        .offset(offset)
    )

    rows = result.all()

    return [
        DoctorListItem(
            id=doctor.id,
            name=user.full_name,
            email=user.email,
            specialization=doctor.specialization,
            experience_years=doctor.experience_years,
            bio=doctor.bio,
        )
        for doctor, user in rows
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

    return DoctorSignatureResponse(
        signature_file_path=doctor.signature_file_path,
        signature_uploaded_at=doctor.signature_uploaded_at,
    )