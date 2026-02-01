from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException,status

from app.models.doctor import Doctor
from app.models.doctor_availability import DoctorAvailability
from app.models.user import User, UserRole
from app.models import user


async def _get_doctor_or_403(db: AsyncSession, user: User) -> Doctor:
    if user.role != UserRole.DOCTOR:
        raise HTTPException(403, "Only doctors allowed")

    result = await db.execute(
        select(Doctor).where(Doctor.user_id == user.id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(404, "Doctor profile not found")

    if not doctor.is_verified:
        raise HTTPException(403, "Doctor not verified")
    
    if not doctor.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor account suspended",
    )
    if not doctor.user.is_active:
        raise HTTPException(403, "Doctor account suspended")




    return doctor


# CREATE

async def create_availability(
    db: AsyncSession,
    user: User,
    day_of_week: int,
    start_time,
    end_time,
):
    doctor = await _get_doctor_or_403(db, user)

    if start_time >= end_time:
        raise HTTPException(400, "Invalid time range")

    availability = DoctorAvailability(
        doctor_id=doctor.id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
    )

    db.add(availability)
    await db.commit()
    await db.refresh(availability)
    return availability



# DOCTOR: list own availability

async def list_my_availability(
    db: AsyncSession,
    user: User,
):
    doctor = await _get_doctor_or_403(db, user)

    result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.doctor_id == doctor.id
        )
    )
    return result.scalars().all()



# PUBLIC: list by doctor_id

async def list_availability(
    db: AsyncSession,
    doctor_id: int,
):
    result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.doctor_id == doctor_id,
            DoctorAvailability.is_available.is_(True),
        )
    )
    return result.scalars().all()


# UPDATE

async def update_availability(
    db: AsyncSession,
    user: User,
    availability_id: int,
    data: dict,
):
    doctor = await _get_doctor_or_403(db, user)

    result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.id == availability_id,
            DoctorAvailability.doctor_id == doctor.id,
        )
    )
    availability = result.scalar_one_or_none()

    if not availability:
        raise HTTPException(404, "Availability not found")

    for key, value in data.items():
        if value is not None:
            setattr(availability, key, value)

    await db.commit()
    await db.refresh(availability)
    return availability


# DELETE

async def delete_availability(
    db: AsyncSession,
    user: User,
    availability_id: int,
):
    doctor = await _get_doctor_or_403(db, user)

    result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.id == availability_id,
            DoctorAvailability.doctor_id == doctor.id,
        )
    )
    availability = result.scalar_one_or_none()

    if not availability:
        raise HTTPException(404, "Availability not found")

    await db.delete(availability)
    await db.commit()



