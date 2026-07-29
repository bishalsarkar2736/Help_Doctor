from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_availability import DoctorAvailability
from app.models.user import User, UserRole
from app.try_except.exceptions import ForbiddenError,NotFoundError,BadRequestError,ConflictError
from app.core.cache import get_cache, set_cache, delete_cache
from sqlalchemy.orm import selectinload

async def _get_doctor_or_403(db: AsyncSession, user: User) -> Doctor:
    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("Only doctors allowed")

    result = await db.execute(
        select(Doctor)
        .options(selectinload(Doctor.user))
        .where(Doctor.user_id == user.id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise NotFoundError("Doctor profile not found")

    if doctor.status != DoctorStatus.APPROVED:
        raise ForbiddenError("Doctor not verified")
    
    if not doctor.user.is_active:
        raise ForbiddenError("Doctor account suspended")

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
        raise BadRequestError("Invalid time range")
    
      # 2️⃣ Validate day_of_week
    if day_of_week < 0 or day_of_week > 6:
        raise BadRequestError("day_of_week must be between 0 and 6")

    # 3️⃣ Check overlapping availability
    result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.doctor_id == doctor.id,
            DoctorAvailability.day_of_week == day_of_week,
            DoctorAvailability.is_available.is_(True),
            DoctorAvailability.start_time < end_time,
            DoctorAvailability.end_time > start_time,
        )
    )

    conflict = result.scalar_one_or_none()

    if conflict:
        raise ConflictError("Availability overlaps with existing schedule")


    availability = DoctorAvailability(
        doctor_id=doctor.id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
    )

    db.add(availability)
    await db.flush()
    await db.refresh(availability)

    await delete_cache(f"doctor_availability:{doctor.id}")

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

    cache_key = f"doctor_availability:{doctor_id}"

    cached = await get_cache(cache_key)
    if cached:
        return cached

    result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.doctor_id == doctor_id,
            DoctorAvailability.is_available.is_(True),
        )
    )

    slots = result.scalars().all()

    data = [
        {
            "id": s.id,
            "day_of_week": s.day_of_week,
            "start_time": str(s.start_time),
            "end_time": str(s.end_time),
        }
        for s in slots
    ]

    await set_cache(cache_key, data, ttl=60)

    return data


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
        raise NotFoundError("Availability not found")

    allowed_fields = {"day_of_week", "start_time", "end_time", "is_available"}

    # #for key, value in data.items():
    #     if value is not None:
    #         setattr(availability, key, value)
    for key in allowed_fields:
        if key in data and data[key] is not None:
            setattr(availability, key, data[key])

    # ✅ Overlap check (exclude current row)
    result = await db.execute(
        select(DoctorAvailability).where(
            DoctorAvailability.doctor_id == doctor.id,
            DoctorAvailability.day_of_week == availability.day_of_week,
            DoctorAvailability.is_available.is_(True),
            DoctorAvailability.id != availability.id,
            DoctorAvailability.start_time < availability.end_time,
            DoctorAvailability.end_time > availability.start_time,
        )
    )

    conflict = result.scalar_one_or_none()

    if conflict:
        raise BadRequestError("Availability overlaps with existing schedule")
    

    await db.flush()
    await db.refresh(availability)

    await delete_cache(f"doctor_availability:{doctor.id}")

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
        raise NotFoundError("Availability not found")

    await db.delete(availability)
    await db.flush()

    await delete_cache(f"doctor_availability:{doctor.id}")




