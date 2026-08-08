
from datetime import datetime, time, timedelta, date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.clinics.visibility import clinic_is_public
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.doctor_slot import DoctorSlot
from app.domain.scheduling.occupancy import slot_is_blocked
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

    # NOT CACHED, DELIBERATELY.
    #
    # This response was held for 300 seconds. Availability is now derived from
    # appointments, and caching a derived value for five minutes reproduces the
    # bug the derivation exists to fix: somebody books 10:00 and every other
    # patient is still shown 10:00 as free until the entry expires. They pick
    # it, and the exclusion constraint refuses them.
    #
    # Invalidating instead would mean deleting every key that could contain the
    # slot — each date, day-count, limit, offset and only_available combination
    # — from the booking path. That is a second source of truth wearing a
    # different hat, and it fails in the same direction.
    #
    # What the cache bought was one indexed range scan on doctor_slots. What it
    # cost was showing patients times they cannot have. The occupancy check
    # rides the GiST index that already backs the exclusion constraint.
    #
    # /slots is public and unauthenticated, so this endpoint is now one query
    # per request with nothing in front of it. Worth a rate limit; noted rather
    # than added here, because it is a separate decision from correctness.
    is_blocked = slot_is_blocked()

    query = select(
        DoctorSlot.id,
        DoctorSlot.start_time,
        DoctorSlot.end_time,
        is_blocked.label("is_booked"),
    ).where(
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.start_time >= start_dt,
        DoctorSlot.start_time < end_dt,
    )

    if only_available:
        # Filtered in SQL rather than after the fact, so limit and offset
        # paginate the available slots instead of paginating everything and
        # then removing rows from the page.
        query = query.where(~is_blocked)

    query = query.order_by(DoctorSlot.start_time).limit(limit).offset(offset)

    rows = (await db.execute(query)).all()

    # `is_booked` is kept in the response. It is now computed rather than
    # stored, but clients read this key and the contract has not changed.
    return [
        {
            "id": row.id,
            "start_time": row.start_time.isoformat(),
            "end_time": row.end_time.isoformat(),
            "is_booked": row.is_booked,
        }
        for row in rows
    ]
