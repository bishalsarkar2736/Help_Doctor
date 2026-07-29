
from datetime import datetime, timedelta, date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.doctor_slot import DoctorSlot
from app.core.time import UTC
from app.core.cache import get_cache, set_cache


async def get_doctor_slots(
    db: AsyncSession,
    doctor_id: int,
    start_date: date,
    days: int = 1,
    only_available: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    cache_key = (
        f"doctor:{doctor_id}:slots:"
        f"{start_date.isoformat()}:{days}:{only_available}:{limit}:{offset}"
    )

    # 🔹 Cache
    cached = await get_cache(cache_key)
    if cached:
        return cached

    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end_dt = start_dt + timedelta(days=days)

    query = select(DoctorSlot).where(
        DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.start_time >= start_dt,
        DoctorSlot.start_time < end_dt,
    )

    # 🔹 Filter
    if only_available:
        query = query.where(DoctorSlot.is_booked.is_(False))

    # 🔹 Order + Pagination
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