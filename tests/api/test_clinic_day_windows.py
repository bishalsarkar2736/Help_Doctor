"""A clinic day means the clinic's day, everywhere it is asked for.

These tests are built to FAIL against the previous implementation. Every
appointment and payment below sits in the six hours where a UTC day and a Dhaka
day disagree — the only times that tell the two apart. Anything at 09:00 or
14:00 local falls inside both windows and would prove nothing.

    UTC day for 2026-03-10  ->  06:00 on the 10th to 06:00 on the 11th, LOCAL
    Dhaka day for the same  ->  00:00 to 24:00 on the 10th, local

So a row at 00:30 local belongs to the 10th and the UTC window misses it; a row
at 02:00 local on the 11th belongs to the 11th and the UTC window counts it as
the 10th.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from sqlalchemy.dialects.postgresql import Range

from app.core.time import UTC
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User, UserRole
from app.utils.clinic_time import (
    clinic_today,
    get_clinic_day_window,
    get_clinic_month_window,
)

DHAKA = ZoneInfo("Asia/Dhaka")
TARGET = date(2026, 3, 10)


def _utc(day: date, hour: int, minute: int = 0) -> datetime:
    """A clinic-local wall clock, as the instant actually stored."""
    return datetime.combine(day, time(hour, minute), tzinfo=DHAKA).astimezone(UTC)


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


def test_a_day_runs_local_midnight_to_local_midnight():
    start, end = get_clinic_day_window("Asia/Dhaka", TARGET)

    assert start == datetime(2026, 3, 9, 18, 0, tzinfo=UTC)
    assert end == datetime(2026, 3, 10, 18, 0, tzinfo=UTC)


def test_the_window_is_half_open():
    """23:59:59 drops the last second of a day; a half-open interval cannot."""
    start, end = get_clinic_day_window("Asia/Dhaka", TARGET)
    next_start, _ = get_clinic_day_window("Asia/Dhaka", TARGET + timedelta(days=1))

    assert end == next_start


def test_a_utc_clinic_is_unchanged():
    start, end = get_clinic_day_window("UTC", TARGET)

    assert start == datetime(2026, 3, 10, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 3, 11, 0, 0, tzinfo=UTC)


def test_an_unknown_timezone_falls_back_to_utc():
    """A bad value must degrade, not crash a reporting endpoint."""
    assert get_clinic_day_window("Not/AZone", TARGET) == get_clinic_day_window(
        "UTC", TARGET
    )


def test_a_dst_day_is_still_one_calendar_day():
    start, end = get_clinic_day_window("America/New_York", date(2026, 3, 8))

    assert end - start == timedelta(hours=23)


def test_a_month_starts_where_its_first_day_starts():
    month_start, _ = get_clinic_month_window("Asia/Dhaka", date(2026, 3, 17))
    day_start, _ = get_clinic_day_window("Asia/Dhaka", date(2026, 3, 1))

    assert month_start == day_start


def test_a_month_ends_where_the_next_one_starts():
    _, month_end = get_clinic_month_window("Asia/Dhaka", date(2026, 3, 17))
    next_start, _ = get_clinic_day_window("Asia/Dhaka", date(2026, 4, 1))

    assert month_end == next_start


def test_today_is_the_clinics_today():
    """utc_now().date() is the server's date, and differs for six hours daily."""
    assert clinic_today("Asia/Dhaka") == datetime.now(DHAKA).date()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def clinic(db):
    clinic = Clinic(
        name="Dhaka Clinic", status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka"
    )
    db.add(clinic)
    await db.commit()
    return clinic


@pytest.fixture
async def doctor(db, clinic):
    user = User(
        email="tzdoc@test.com",
        full_name="Dr Tz",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=clinic.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.commit()
    return doctor


async def _appointment(db, clinic, doctor, patient_id, when: datetime):
    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor.id,
        clinic_id=clinic.id,
        scheduled_at=when,
        status=AppointmentStatus.PENDING,
        # NOT NULL, and backs the gist exclusion constraint that stops a doctor
        # being double-booked. Built from the same instant so the range and
        # scheduled_at cannot disagree.
        time_range=Range(when, when + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()
    return appointment


# ---------------------------------------------------------------------------
# Appointment search — the boundary hours
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_the_clinics_whole_day(
    db, clinic, doctor, patient_user
):
    """00:30 and 02:00 local belong to this clinic day.

    Both are on the PREVIOUS UTC day, so the old window excluded them from
    their own date entirely.
    """
    from app.services.appointment_search_service import search_appointments

    for hour, minute in ((0, 30), (2, 0), (5, 30), (23, 30)):
        await _appointment(
            db, clinic, doctor, patient_user.id, _utc(TARGET, hour, minute)
        )
    await db.commit()

    results = await search_appointments(
        db=db, clinic_id=clinic.id, date=TARGET, limit=50
    )

    assert len(results) == 4


@pytest.mark.asyncio
async def test_search_excludes_the_next_local_day(
    db, clinic, doctor, patient_user
):
    """02:00 on the 11th is 20:00 UTC on the 10th — counted as the 10th before."""
    from app.services.appointment_search_service import search_appointments

    await _appointment(
        db, clinic, doctor, patient_user.id, _utc(TARGET, 14, 0)
    )
    await _appointment(
        db, clinic, doctor, patient_user.id, _utc(TARGET + timedelta(days=1), 2, 0)
    )
    await db.commit()

    results = await search_appointments(
        db=db, clinic_id=clinic.id, date=TARGET, limit=50
    )

    assert len(results) == 1


@pytest.mark.asyncio
async def test_a_date_range_covers_whole_local_days(
    db, clinic, doctor, patient_user
):
    """The end date must include its own late evening, not stop at 06:00."""
    from app.services.appointment_search_service import search_appointments

    await _appointment(db, clinic, doctor, patient_user.id, _utc(TARGET, 0, 30))
    await _appointment(db, clinic, doctor, patient_user.id, _utc(TARGET, 23, 30))
    await db.commit()

    results = await search_appointments(
        db=db,
        clinic_id=clinic.id,
        start_date=TARGET,
        end_date=TARGET,
        limit=50,
    )

    assert len(results) == 2


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_calendar_covers_whole_local_days(
    db, clinic, doctor, patient_user
):
    from app.services.appointment_calendar_service import get_calendar_appointments

    await _appointment(db, clinic, doctor, patient_user.id, _utc(TARGET, 0, 30))
    await _appointment(db, clinic, doctor, patient_user.id, _utc(TARGET, 23, 30))
    await _appointment(
        db, clinic, doctor, patient_user.id, _utc(TARGET + timedelta(days=1), 2, 0)
    )
    await db.commit()

    results = await get_calendar_appointments(
        db=db, clinic_id=clinic.id, start_date=TARGET, end_date=TARGET
    )

    assert len(results) == 2


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todays_revenue_uses_the_clinics_day(db, clinic, doctor, patient_user):
    """A payment taken at 01:00 local today is on yesterday's UTC date.

    The old window reported it as yesterday's takings and counted six hours of
    tomorrow's as today's.
    """
    from app.models.payment import Payment, PaymentStatus
    from app.services.revenue_analytics_service import get_revenue_today

    today_local = clinic_today("Asia/Dhaka")

    appointment = await _appointment(
        db, clinic, doctor, patient_user.id, _utc(today_local, 1, 0)
    )

    db.add(
        Payment(
            appointment_id=appointment.id,
            patient_id=patient_user.id,
            clinic_id=clinic.id,
            amount=Decimal("500.00"),
            method="bkash",
            status=PaymentStatus.SUCCESS,
            created_at=_utc(today_local, 1, 0),
        )
    )
    await db.commit()

    assert await get_revenue_today(db=db, clinic_id=clinic.id) == 500.0
