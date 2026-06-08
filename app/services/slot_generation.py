from datetime import datetime, timedelta

from sqlalchemy import select, text
from app.db.postgres import AsyncSessionLocal
from app.models.doctor_availability import DoctorAvailability
from app.models.doctor_slot import DoctorSlot
from app.core.time import UTC


SLOT_DURATION_MINUTES = 30
DAYS_AHEAD = 7

# 🔒 unique lock id (any constant int)
SLOT_JOB_LOCK_ID = 123456789


async def generate_slots():

    async with AsyncSessionLocal() as db:

        # 🔒 acquire advisory lock
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": SLOT_JOB_LOCK_ID},
        )

        locked = result.scalar()

        if not locked:
            # another worker is running this job
            return

        try:
            now = datetime.now(UTC)
            end_date = now + timedelta(days=DAYS_AHEAD)

            # get all availability rules
            result = await db.execute(select(DoctorAvailability))
            rules = result.scalars().all()

            for rule in rules:

                if not rule.is_available:
                    continue

                current_date = now.date()

                while current_date <= end_date.date():

                    if current_date.weekday() != rule.day_of_week:
                        current_date += timedelta(days=1)
                        continue

                    start_dt = datetime.combine(current_date, rule.start_time, tzinfo=UTC)
                    end_dt = datetime.combine(current_date, rule.end_time, tzinfo=UTC)

                    slot_start = start_dt

                    while slot_start < end_dt:

                        slot_end = slot_start + timedelta(minutes=SLOT_DURATION_MINUTES)

                        # check if slot already exists
                        exists_stmt = select(DoctorSlot).where(
                            DoctorSlot.doctor_id == rule.doctor_id,
                            DoctorSlot.start_time == slot_start,
                        )

                        exists = await db.execute(exists_stmt)

                        if not exists.scalar_one_or_none():
                            slot = DoctorSlot(
                                doctor_id=rule.doctor_id,
                                start_time=slot_start,
                                end_time=slot_end,
                            )
                            db.add(slot)

                        slot_start = slot_end

                    current_date += timedelta(days=1)

            await db.commit()

        finally:
            # 🔓 release advisory lock
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": SLOT_JOB_LOCK_ID},
            )