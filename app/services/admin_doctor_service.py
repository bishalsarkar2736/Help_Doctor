from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.doctor import Doctor
from app.models.user import User, UserRole


async def _admin_only(user: User):
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


async def verify_doctor(
    db: AsyncSession,
    admin: User,
    doctor_id: int,
):
    await _admin_only(admin)

    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor not found")

    doctor.is_verified = True
    await db.commit()

    return {"message": "Doctor verified successfully"}


async def suspend_doctor(
    db: AsyncSession,
    admin: User,
    doctor_id: int,
):
    await _admin_only(admin)

    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor not found")

    # Suspend via user
    doctor.user.is_active = False
    await db.commit()

    return {"message": "Doctor suspended"}


async def unsuspend_doctor(
    db: AsyncSession,
    admin: User,
    doctor_id: int,
):
    await _admin_only(admin)

    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor not found")

    doctor.user.is_active = True
    await db.commit()

    return {"message": "Doctor unsuspended"}


async def activate_doctor(
    db: AsyncSession,
    doctor_id: int,
    admin: User,
):
    await _admin_only(admin)

    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor not found")

    doctor.user.is_active = True
    await db.commit()

    return {"message": "Doctor activated"}

