
from datetime import datetime, time, timedelta, date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.clinics.visibility import clinic_is_public
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.doctor_slot import DoctorSlot
from app.core.cache import get_cache, set_cache
from app.core.time import UTC
from app.utils.clinic_time import doctor_clinic_timezone, get_clinic_day_window


async def doctor_is_publicly_bookable(db: AsyncSession, doctor_id: int) -> bool:
    """Whether this doctor's clinic is open to the public.

    Uses the shared predicate, so the slot list, the doctor directory and the
    assistant cannot disagree about whether a clinic is available.
    """
    found = await db.scalar(
        select(Doctor.id)
        .join(Clinic, Doctor.clinic_id == Clinic.id)
        .where(Doctor.id == doctor_id, *clinic_is_public())
    )

    return found is not None


async def get_doctor_slots(
    db: AsyncSession,
    doctor_id: int,
    start_date: date,
    days: int = 1,
    only_available: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    """Slots on the given calendar days, as the CLINIC reckons days.

    `start_date` is a date with no timezone of its own, and it used to be read
    as a UTC day boundary while the slots it filtered were generated from
    clinic-local availability. For a clinic at UTC+6 that made "today" run from
    06:00 to 06:00 local: the first six hours of the requested day were missing
    and six hours of the next day were included. The further a clinic is from
    UTC the more of its morning disappeared.
    """
    # A suspended or deleted clinic is offline: its slots stay in the table so
    # recovery is instant, but they are not offered publicly.
    if not await doctor_is_publicly_bookable(db, doctor_id):
        return []

    tz_name = await doctor_clinic_timezone(db, doctor_id)

    start_dt, end_dt = get_clinic_day_window(tz_name, start_date, days)

    # The timezone belongs in the cache key. The same doctor_id and date map to
    # a different UTC window if the clinic's timezone is corrected, and the key
    # without it would keep serving the window computed under the old one.
    cache_key = (
        f"doctor:{doctor_id}:slots:"
        f"{start_date.isoformat()}:{days}:{only_available}:{limit}:{offset}:"
        f"{start_dt.isoformat()}"
    )

    cached = await get_cache(cache_key)
    if cached:
        return cached

    query = select(DoctorSlot).where(
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.start_time >= start_dt,
        DoctorSlot.start_time < end_dt,
    )

    if only_available:
        query = query.where(DoctorSlot.is_booked.is_(False))

    query = query.order_by(DoctorSlot.start_time).limit(limit).offset(offset)

    result = await db.execute(query)
    slots = result.scalars().all()

    data = [
        {
            "id": s.id,
            "start_time": s.start_time.isoformat(),
            "end_time": s.end_time.isoformat(),
            "is_booked": s.is_booked,
        }
        for s in slots
    ]

    await set_cache(cache_key, data, ttl=300)

    return data
