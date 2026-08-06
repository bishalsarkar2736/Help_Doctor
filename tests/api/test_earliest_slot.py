"""The soonest a patient can be seen at ONE clinic.

Answers "who can see me today?". The tenant scoping is the part that matters:
HelpDoctor is multi-tenant and not a marketplace, so surfacing a doctor from
another clinic would be a breach, not a helpful suggestion.
"""

from datetime import timedelta

import pytest

from app.core.time import utc_now
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_slot import DoctorSlot
from app.models.user import User, UserRole
from app.services.earliest_slot_service import find_earliest_available_doctor


@pytest.fixture
async def two_clinics(db):
    """Two clinics, each with one doctor holding free slots."""
    clinics = {}

    for key, name in (("ours", "Our Clinic"), ("theirs", "Their Clinic")):
        clinic = Clinic(name=name, status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka")
        db.add(clinic)
        await db.flush()
        clinics[key] = clinic

    await db.commit()
    return clinics


async def _doctor(
    db,
    clinic,
    *,
    email,
    name,
    specialization="Cardiology",
    status=DoctorStatus.APPROVED,
    is_active=True,
) -> Doctor:
    user = User(
        email=email,
        full_name=name,
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=clinic.id,
        specialization=specialization,
        experience_years=5,
        bio="Doctor",
        status=status,
    )
    db.add(doctor)
    await db.flush()

    return doctor


async def _slot(db, doctor, *, minutes_from_now, is_booked=False):
    start = utc_now() + timedelta(minutes=minutes_from_now)

    db.add(
        DoctorSlot(
            doctor_id=doctor.id,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            is_booked=is_booked,
        )
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_this_clinics_doctors_are_offered(db, two_clinics):
    """Another clinic's doctor sooner is still another clinic's doctor."""
    ours = await _doctor(db, two_clinics["ours"], email="a@t.com", name="Dr Ours")
    theirs = await _doctor(db, two_clinics["theirs"], email="b@t.com", name="Dr Theirs")

    # Theirs is sooner, so a query that ignored the clinic would pick it.
    await _slot(db, theirs, minutes_from_now=10)
    await _slot(db, ours, minutes_from_now=60)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id
    )

    assert [r["doctor_name"] for r in results] == ["Dr Ours"]


@pytest.mark.asyncio
async def test_a_clinic_with_nothing_free_returns_empty(db, two_clinics):
    """A real answer, not a reason to look next door."""
    theirs = await _doctor(db, two_clinics["theirs"], email="c@t.com", name="Dr Theirs")
    await _slot(db, theirs, minutes_from_now=10)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id
    )

    assert results == []


# ---------------------------------------------------------------------------
# Which slots count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_soonest_slot_wins(db, two_clinics):
    early = await _doctor(db, two_clinics["ours"], email="d@t.com", name="Dr Early")
    late = await _doctor(db, two_clinics["ours"], email="e@t.com", name="Dr Late")

    await _slot(db, late, minutes_from_now=120)
    await _slot(db, early, minutes_from_now=30)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id
    )

    assert results[0]["doctor_name"] == "Dr Early"


@pytest.mark.asyncio
async def test_a_booked_slot_is_not_offered(db, two_clinics):
    doctor = await _doctor(db, two_clinics["ours"], email="f@t.com", name="Dr One")

    await _slot(db, doctor, minutes_from_now=10, is_booked=True)
    await _slot(db, doctor, minutes_from_now=90)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id
    )

    assert len(results) == 1
    assert results[0]["start_time"] > (utc_now() + timedelta(minutes=60)).isoformat()


@pytest.mark.asyncio
async def test_a_past_slot_is_not_offered(db, two_clinics):
    """Without a floor the "earliest" is whatever sits lowest in the table —
    for a clinic that has been running a while, a slot from months ago."""
    doctor = await _doctor(db, two_clinics["ours"], email="g@t.com", name="Dr One")

    await _slot(db, doctor, minutes_from_now=-120)
    await _slot(db, doctor, minutes_from_now=45)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id
    )

    assert len(results) == 1


@pytest.mark.asyncio
async def test_a_floor_can_be_supplied(db, two_clinics):
    """"Who can see me after lunch?" is the same question with a later floor."""
    doctor = await _doctor(db, two_clinics["ours"], email="h@t.com", name="Dr One")

    await _slot(db, doctor, minutes_from_now=30)
    await _slot(db, doctor, minutes_from_now=300)
    await db.commit()

    results = await find_earliest_available_doctor(
        db,
        clinic_id=two_clinics["ours"].id,
        not_before=utc_now() + timedelta(minutes=120),
    )

    assert len(results) == 1


# ---------------------------------------------------------------------------
# Who can be offered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unapproved_doctor_is_not_offered(db, two_clinics):
    pending = await _doctor(
        db,
        two_clinics["ours"],
        email="i@t.com",
        name="Dr Pending",
        status=DoctorStatus.PENDING,
    )
    await _slot(db, pending, minutes_from_now=10)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id
    )

    assert results == []


@pytest.mark.asyncio
async def test_a_deactivated_account_is_not_offered(db, two_clinics):
    """Their slots may still exist; they will not see anyone."""
    inactive = await _doctor(
        db,
        two_clinics["ours"],
        email="j@t.com",
        name="Dr Inactive",
        is_active=False,
    )
    await _slot(db, inactive, minutes_from_now=10)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id
    )

    assert results == []


# ---------------------------------------------------------------------------
# Specialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_specialization_narrows_the_search(db, two_clinics):
    cardio = await _doctor(
        db, two_clinics["ours"], email="k@t.com", name="Dr Heart",
        specialization="Cardiology",
    )
    derm = await _doctor(
        db, two_clinics["ours"], email="l@t.com", name="Dr Skin",
        specialization="Dermatology",
    )

    await _slot(db, derm, minutes_from_now=10)
    await _slot(db, cardio, minutes_from_now=60)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id, specialization="Cardiology"
    )

    assert [r["doctor_name"] for r in results] == ["Dr Heart"]


@pytest.mark.asyncio
async def test_specialization_matching_is_case_insensitive(db, two_clinics):
    """Matched the way GET /doctors matches it, so the two cannot disagree
    about who counts as a cardiologist."""
    cardio = await _doctor(
        db, two_clinics["ours"], email="m@t.com", name="Dr Heart",
        specialization="Cardiology",
    )
    await _slot(db, cardio, minutes_from_now=30)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id, specialization="cardiology"
    )

    assert len(results) == 1


@pytest.mark.asyncio
async def test_an_unmatched_specialization_returns_empty(db, two_clinics):
    doctor = await _doctor(db, two_clinics["ours"], email="n@t.com", name="Dr One")
    await _slot(db, doctor, minutes_from_now=30)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id, specialization="Neurology"
    )

    assert results == []


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_result_carries_what_an_answer_needs(db, two_clinics):
    doctor = await _doctor(db, two_clinics["ours"], email="o@t.com", name="Dr One")
    await _slot(db, doctor, minutes_from_now=30)
    await db.commit()

    result = (
        await find_earliest_available_doctor(db, clinic_id=two_clinics["ours"].id)
    )[0]

    assert set(result) >= {
        "slot_id",
        "doctor_id",
        "doctor_name",
        "specialization",
        "start_time",
        "end_time",
    }


@pytest.mark.asyncio
async def test_several_options_can_be_requested(db, two_clinics):
    doctor = await _doctor(db, two_clinics["ours"], email="p@t.com", name="Dr One")

    for minutes in (30, 60, 90):
        await _slot(db, doctor, minutes_from_now=minutes)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=two_clinics["ours"].id, limit=2
    )

    assert len(results) == 2
    assert results[0]["start_time"] < results[1]["start_time"]
