from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.user import User, UserRole
from app.try_except.exceptions import NotFoundError,ForbiddenError


async def _admin_only(user: User):
    if user.role != UserRole.ADMIN:
        raise ForbiddenError("Admin access required")


async def verify_doctor(
    db: AsyncSession,
    admin: User,
    doctor_id: int,
    clinic_id: int,
):
    await _admin_only(admin)

    result = await db.execute(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise NotFoundError("Doctor not found")
    
    clinic_result = await db.execute(
        select(Clinic)
        .where(Clinic.id == clinic_id)
    )

    clinic = clinic_result.scalar_one_or_none()

    if not clinic:
        raise NotFoundError("Clinic not found")
    

    doctor.clinic_id = clinic.id
    doctor.is_verified = True
    await db.flush()


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
        raise NotFoundError("Doctor not found")

    # Suspend via user
    doctor.user.is_active = False
    await db.flush()


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
        raise NotFoundError("Doctor not found")

    doctor.user.is_active = True
    await db.flush()


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
        raise NotFoundError("Doctor not found")

    doctor.user.is_active = True
    await db.flush()


    return {"message": "Doctor activated"}

