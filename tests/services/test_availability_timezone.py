import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.core.time import UTC
from app.core.tz import to_zoneinfo
from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.clinic import Clinic
from app.models.doctor_availability import DoctorAvailability
from app.domain.scheduling.availability import validate_doctor_availability
from app.try_except.exceptions import BadRequestError


async def _doctor_in_clinic(db, tz_name: str):
    clinic = Clinic(
        name=f"Clinic {uuid.uuid4().hex[:6]}",
        address="X",
        phone="0",
        email=f"{uuid.uuid4().hex[:6]}@t.com",
        timezone=tz_name,
    )
    db.add(clinic)
    await db.flush()

    user = User(
        email=f"doc-{uuid.uuid4()}@t.com",
        full_name="Dr TZ",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
        clinic_id=clinic.id,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=clinic.id,
        specialization="Medicine",
        experience_years=1,
        bio="x",
        status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()
    return doctor


async def _availability(db, doctor_id, weekday):
    db.add(
        DoctorAvailability(
            doctor_id=doctor_id,
            day_of_week=weekday,
            start_time=time(9, 0),
            end_time=time(17, 0),
            is_available=True,
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_booking_validated_in_clinic_local_time(db):
    # Dhaka is UTC+6: 03:00 UTC == 09:00 local (inside 09:00-17:00 availability),
    # even though 03:00 UTC is OUTSIDE the window if read as raw UTC.
    dhaka = ZoneInfo("Asia/Dhaka")
    booking_utc = datetime(2026, 8, 3, 3, 0, tzinfo=UTC)
    local = booking_utc.astimezone(dhaka)

    doctor = await _doctor_in_clinic(db, "Asia/Dhaka")
    await _availability(db, doctor.id, local.weekday())

    # Must NOT raise — 09:00 local is within the availability window.
    await validate_doctor_availability(db, doctor.id, booking_utc)


@pytest.mark.asyncio
async def test_booking_outside_local_window_rejected(db):
    dhaka = ZoneInfo("Asia/Dhaka")
    # 13:00 UTC == 19:00 local — outside 09:00-17:00.
    booking_utc = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)
    local = booking_utc.astimezone(dhaka)

    doctor = await _doctor_in_clinic(db, "Asia/Dhaka")
    await _availability(db, doctor.id, local.weekday())

    with pytest.raises(BadRequestError):
        await validate_doctor_availability(db, doctor.id, booking_utc)


@pytest.mark.asyncio
async def test_utc_clinic_unchanged(db):
    booking_utc = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    doctor = await _doctor_in_clinic(db, "UTC")
    await _availability(db, doctor.id, booking_utc.weekday())
    await validate_doctor_availability(db, doctor.id, booking_utc)


def test_to_zoneinfo_falls_back_to_utc():
    assert to_zoneinfo("Not/AZone") is UTC
    assert to_zoneinfo("") is UTC
    assert to_zoneinfo(None) is UTC
    assert to_zoneinfo("Asia/Dhaka").key == "Asia/Dhaka"
