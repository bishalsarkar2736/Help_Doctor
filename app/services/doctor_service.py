from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.domain.policies.doctor_policy import DoctorPolicy

from app.models.doctor import Doctor
from app.models.user import User
from app.try_except.exceptions import BadRequestError,NotFoundError

async def create_doctor_profile(
    db: AsyncSession,
    user: User,
    specialization: str,
    experience_years: int,
    bio: str,
) -> Doctor:
    
    DoctorPolicy.can_create_profile(user)

    # if user.role != UserRole.DOCTOR:
    #     raise ForbiddenError("User is not a doctor")

    result = await db.execute(
        select(Doctor).where(Doctor.user_id == user.id)
    )
    if result.scalar_one_or_none():
        raise BadRequestError("Doctor profile already exists")

    doctor = Doctor(
        user_id=user.id,
        specialization=specialization,
        experience_years=experience_years,
        bio=bio,
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

    doctor.is_verified = True
    await db.flush()
    await db.refresh(doctor)

    return doctor

