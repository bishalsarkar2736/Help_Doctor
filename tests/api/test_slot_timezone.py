"""Slot listing asks about a calendar day as the CLINIC reckons days.

Availability is entered in clinic-local wall-clock time and slots are stored in
UTC. Reading them back used to treat the requested date as a UTC day boundary,
so for a clinic at UTC+6 "today" ran 06:00 to 06:00 local — the first six hours
of the requested day were missing and six hours of the next day were included.

A human scanning a slot list might notice. The scheduling assistant will say
"Dr Rahman is free tomorrow at 2:00 PM", which makes it authoritative, so this
is pinned before anything phrases it in natural language.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.time import UTC
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_slot import DoctorSlot
from app.models.user import User, UserRole
from app.services.slot_service import get_doctor_slots
from app.utils.clinic_time import get_clinic_day_window

# UTC+6, no DST — the project's own clinics run here, and it is far enough from
# UTC that a day-boundary error is unmissable.
DHAKA = ZoneInfo("Asia/Dhaka")

TARGET_DAY = date(2026, 3, 10)


@pytest.fixture
async def dhaka_doctor(db):
    clinic = Clinic(
        name="Dhaka Clinic",
        status=ClinicStatus.ACTIVE,
        timezone="Asia/Dhaka",
    )
    db.add(clinic)
    await db.flush()

    user = User(
        email="dhaka-doc@test.com",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=clinic.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()

    def _slot(local_dt: datetime) -> DoctorSlot:
        start = local_dt.replace(tzinfo=DHAKA).astimezone(UTC)
        return DoctorSlot(
            doctor_id=doctor.id,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            is_booked=False,
        )

    # The UTC day 00:00-24:00 corresponds to 06:00-06:00 local here, so the
    # only times that tell the two windows apart are those before 06:00 local.
    # A slot at 09:00 or 14:00 is inside both and proves nothing.
    db.add_all(
        [
            # 02:00 local = 20:00 UTC the PREVIOUS day. The old window began at
            # 06:00 local, so this was dropped from its own clinic day.
            _slot(datetime.combine(TARGET_DAY, time(2, 0))),
            _slot(datetime.combine(TARGET_DAY, time(14, 0))),
            # 23:30 local is inside both windows.
            _slot(datetime.combine(TARGET_DAY, time(23, 30))),
            # 02:00 the NEXT local day = 20:00 UTC today. The old window ran to
            # 06:00 the following morning, so this leaked in as "today".
            _slot(datetime.combine(TARGET_DAY + timedelta(days=1), time(2, 0))),
            # Clearly outside either reading.
            _slot(datetime.combine(TARGET_DAY - timedelta(days=1), time(22, 0))),
        ]
    )
    await db.commit()
    return doctor


def _local_times(slots) -> list[str]:
    return [
        datetime.fromisoformat(s["start_time"]).astimezone(DHAKA).strftime("%H:%M")
        for s in slots
    ]


@pytest.mark.asyncio
async def test_a_day_covers_the_clinics_local_day(db, dhaka_doctor):
    slots = await get_doctor_slots(db, dhaka_doctor.id, TARGET_DAY, days=1)

    assert _local_times(slots) == ["02:00", "14:00", "23:30"]


@pytest.mark.asyncio
async def test_an_early_morning_slot_is_not_dropped(db, dhaka_doctor):
    """02:00 in Dhaka is 20:00 UTC the day BEFORE.

    The old window started at 06:00 local, so a patient asking about this day
    was never shown its own early-morning slots.
    """
    slots = await get_doctor_slots(db, dhaka_doctor.id, TARGET_DAY, days=1)

    assert "02:00" in _local_times(slots)


@pytest.mark.asyncio
async def test_the_next_local_day_does_not_leak_in(db, dhaka_doctor):
    """The old window ran to 06:00 the next morning, so 02:00 tomorrow was
    offered as though it were today — the assistant would name a time on the
    wrong date."""
    slots = await get_doctor_slots(db, dhaka_doctor.id, TARGET_DAY, days=1)

    tomorrow_early = [
        s
        for s in slots
        if datetime.fromisoformat(s["start_time"]).astimezone(DHAKA).date()
        != TARGET_DAY
    ]

    assert tomorrow_early == []
    assert len(slots) == 3


@pytest.mark.asyncio
async def test_the_previous_local_day_is_excluded(db, dhaka_doctor):
    slots = await get_doctor_slots(db, dhaka_doctor.id, TARGET_DAY, days=1)

    starts = [datetime.fromisoformat(s["start_time"]) for s in slots]
    earliest_local = min(starts).astimezone(DHAKA)

    assert earliest_local.date() == TARGET_DAY


@pytest.mark.asyncio
async def test_a_multi_day_window_spans_whole_local_days(db, dhaka_doctor):
    slots = await get_doctor_slots(db, dhaka_doctor.id, TARGET_DAY, days=2)

    assert _local_times(slots) == ["02:00", "14:00", "23:30", "02:00"]


@pytest.mark.asyncio
async def test_only_available_still_filters(db, dhaka_doctor):
    slots = await get_doctor_slots(
        db, dhaka_doctor.id, TARGET_DAY, days=1, only_available=True
    )

    assert len(slots) == 3


# ---------------------------------------------------------------------------
# The window itself
# ---------------------------------------------------------------------------


def test_the_window_is_built_from_local_midnight():
    start, end = get_clinic_day_window("Asia/Dhaka", TARGET_DAY)

    # Dhaka is UTC+6, so local midnight is 18:00 UTC the previous day.
    assert start == datetime(2026, 3, 9, 18, 0, tzinfo=UTC)
    assert end == datetime(2026, 3, 10, 18, 0, tzinfo=UTC)


def test_a_utc_clinic_is_unaffected():
    """The behaviour that was already correct must not change."""
    start, end = get_clinic_day_window("UTC", TARGET_DAY)

    assert start == datetime(2026, 3, 10, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 3, 11, 0, 0, tzinfo=UTC)


def test_a_dst_day_is_still_one_calendar_day():
    """New York loses an hour on 2026-03-08.

    Adding 24 hours would overshoot into the next local day; going local
    midnight to local midnight covers exactly the day asked for.
    """
    start, end = get_clinic_day_window("America/New_York", date(2026, 3, 8))

    assert (end - start) == timedelta(hours=23)
