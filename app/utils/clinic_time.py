"""What a clinic means by "a day".

THE ONE IMPLEMENTATION
----------------------
Every window over a calendar day, month, or "today" is built here. Six places
used to compute it independently, and the ones that got it wrong got it wrong
in the same way: they treated a date as a UTC day boundary while the rows they
filtered were written in the clinic's local time.

    datetime.combine(target, time.min, tzinfo=UTC)   # WRONG for a clinic day

For a clinic at UTC+6 that runs 06:00 to 06:00 local. A doctor's "today" then
begins at six in the morning and ends at six the next morning: their early
appointments are missing and tomorrow's early ones are counted as today's.
Today's revenue includes six hours of tomorrow.

The correct window is local midnight to local midnight, converted to UTC:

    00:00 local  ->  start_utc
    00:00 local next day  ->  end_utc     (exclusive)

END IS EXCLUSIVE, NOT 23:59:59
------------------------------
An end of 23:59:59 silently drops the final second of the day, and with
microsecond precision drops almost a whole second of rows. A half-open interval
[start, end) has no gap and no overlap when windows are placed side by side.

BUILT FROM LOCAL MIDNIGHTS, NOT BY ADDING 24 HOURS
--------------------------------------------------
A day crossing a DST transition is 23 or 25 hours long. Adding a fixed 24 hours
would overshoot or undershoot into the neighbouring day. Taking local midnight
on each end covers exactly the days requested whatever their length.
"""

from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import UTC
from app.core.tz import to_zoneinfo
from app.models.clinic import Clinic
from app.models.doctor import Doctor


def clinic_today(clinic_timezone: str | None) -> date:
    """Today, as the clinic reckons it.

    date.today() and utc_now().date() are the SERVER's date. With the API in
    UTC and a clinic at UTC+6 the two disagree for six hours of every day —
    long enough for "today's revenue" to report yesterday's every evening.
    """
    return datetime.now(to_zoneinfo(clinic_timezone)).date()


def get_clinic_day_window(
    clinic_timezone: str | None,
    target_date: date,
    days: int = 1,
) -> tuple[datetime, datetime]:
    """UTC bounds of `days` calendar days starting on `target_date`, in `tz`.

    Half-open: start inclusive, end exclusive.
    """
    tz = to_zoneinfo(clinic_timezone)

    start_local = datetime.combine(target_date, time.min, tzinfo=tz)
    end_local = datetime.combine(target_date + timedelta(days=days), time.min, tzinfo=tz)

    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def get_clinic_month_window(
    clinic_timezone: str | None,
    any_date_in_month: date,
) -> tuple[datetime, datetime]:
    """UTC bounds of the calendar month containing `any_date_in_month`.

    Derived from the day window so a month begins exactly where its first day
    does — one definition of a boundary, not two that can drift apart.
    """
    first = any_date_in_month.replace(day=1)
    next_first = first + relativedelta(months=1)

    start, _ = get_clinic_day_window(clinic_timezone, first)
    next_start, _ = get_clinic_day_window(clinic_timezone, next_first)

    return start, next_start


async def clinic_timezone(db: AsyncSession, clinic_id: int) -> str | None:
    """The IANA timezone of a clinic. Blank or unknown falls back to UTC later.

    Read once per request and passed down. Resolving it inside a loop would
    query per row for a value that cannot change mid-request.
    """
    return await db.scalar(select(Clinic.timezone).where(Clinic.id == clinic_id))


async def doctor_clinic_timezone(db: AsyncSession, doctor_id: int) -> str | None:
    """The timezone of the clinic a doctor practises at."""
    return await db.scalar(
        select(Clinic.timezone)
        .join(Doctor, Doctor.clinic_id == Clinic.id)
        .where(Doctor.id == doctor_id)
    )
