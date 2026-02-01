from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.doctor import Doctor
from app.models.user import User, UserRole


async def create_doctor_profile(
    db: AsyncSession,
    user: User,
    specialization: str,
    experience_years: int,
    bio: str,
) -> Doctor:

    if user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a doctor",
        )

    result = await db.execute(
        select(Doctor).where(Doctor.user_id == user.id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Doctor profile already exists",
        )

    doctor = Doctor(
        user_id=user.id,
        specialization=specialization,
        experience_years=experience_years,
        bio=bio,
    )

    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)

    return doctor


async def verify_doctor(
    db: AsyncSession,
    doctor_id: int,
):
    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor not found")

    doctor.is_verified = True
    await db.commit()
