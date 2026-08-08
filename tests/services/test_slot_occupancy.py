"""Slot availability is derived from appointments, not stored.

doctor_slots carried an is_booked column that nothing ever set. Every slot
reported itself free forever: the public list offered booked times,
only_available filtered nothing, the assistant recommended occupied slots, and
utilisation read zero. Patients picked a slot the screen called free and were
then refused by the exclusion constraint.

These tests are written so that they would all have PASSED against a stored flag
that was being maintained correctly, and all FAIL against the flag as it
actually was. What they pin is the behaviour — a booked slot is unavailable, a
cancellation gives it back — rather than the mechanism.

The last test pins the mechanism, because "derived" is the property that stops
this recurring: there is no column to fall out of date.
"""

from datetime import timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.postgresql import Range

from app.core.constants import APPOINTMENT_DURATION_MINUTES
from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_slot import DoctorSlot
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.earliest_slot_service import find_earliest_available_doctor
from app.services.slot_service import get_doctor_slots

SLOT = timedelta(minutes=APPOINTMENT_DURATION_MINUTES)


@pytest.fixture
async def clinic_with_slots(db):
    """A doctor with three consecutive future slots, none booked."""
    clinic = Clinic(
        name="Occupancy Clinic", status=ClinicStatus.ACTIVE, timezone="UTC"
    )
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email="occupancy-doc@example.com", full_name="Dr Occupancy",
        hashed_password="x", role=UserRole.DOCTOR, is_active=True,
        clinic_id=clinic.id,
    )
    db.add(doctor_user)
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=5, bio="b", status=DoctorStatus.APPROVED,
        consultation_fee=500,
    )
    db.add(doctor)
    await db.flush()

    # Tomorrow, so "future" is not sensitive to the hour the suite runs.
    base = (utc_now() + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )

    slots = []
    for index in range(3):
        start = base + index * SLOT
        slot = DoctorSlot(
            doctor_id=doctor.id, start_time=start, end_time=start + SLOT
        )
        db.add(slot)
        slots.append(slot)

    await db.flush()

    patient = User(
        email="occupancy-patient@example.com", full_name="Occupancy Patient",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(patient)
    await db.flush()

    db.add(Patient(
        user_id=patient.id, phone="+8801933000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    return {
        "clinic": clinic,
        "doctor": doctor,
        "patient": patient,
        "slots": slots,
        "date": base.date(),
    }


async def _book(db, ctx, slot, *, status=AppointmentStatus.CONFIRMED):
    appointment = Appointment(
        patient_id=ctx["patient"].id,
        doctor_id=ctx["doctor"].id,
        clinic_id=ctx["clinic"].id,
        scheduled_at=slot.start_time,
        status=status,
        time_range=Range(slot.start_time, slot.end_time),
        # Required by chk_cancelled_requires_timestamp when creating a row
        # that is already cancelled.
        cancelled_at=(
            utc_now() if status == AppointmentStatus.CANCELLED else None
        ),
    )
    db.add(appointment)
    await db.flush()
    return appointment


async def _cancel(db, appointment):
    """The database requires cancelled_at on a cancelled appointment
    (chk_cancelled_requires_timestamp), so setting the status alone builds a
    row the schema rejects."""
    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancelled_at = utc_now()
    await db.flush()


async def _listing(db, ctx, *, only_available=False):
    return await get_doctor_slots(
        db=db,
        doctor_id=ctx["doctor"].id,
        start_date=ctx["date"],
        days=1,
        only_available=only_available,
    )


def _by_start(rows):
    return {row["start_time"]: row["is_booked"] for row in rows}


# ---------------------------------------------------------------------------
# The basic claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unbooked_slot_is_available(db, clinic_with_slots):
    rows = await _listing(db, clinic_with_slots)

    assert len(rows) == 3
    assert all(row["is_booked"] is False for row in rows)


@pytest.mark.asyncio
async def test_a_booked_slot_is_unavailable(db, clinic_with_slots):
    """The failure that shipped: this returned False for a booked slot."""
    taken = clinic_with_slots["slots"][1]
    await _book(db, clinic_with_slots, taken)

    availability = _by_start(await _listing(db, clinic_with_slots))

    assert availability[taken.start_time.isoformat()] is True

    # And only that one.
    assert sum(1 for booked in availability.values() if booked) == 1


@pytest.mark.asyncio
async def test_a_pending_appointment_also_blocks(db, clinic_with_slots):
    """PENDING is in the exclusion constraint's set, so it must block here too
    — otherwise the list offers a slot the database will refuse."""
    taken = clinic_with_slots["slots"][0]
    await _book(
        db, clinic_with_slots, taken, status=AppointmentStatus.PENDING
    )

    availability = _by_start(await _listing(db, clinic_with_slots))

    assert availability[taken.start_time.isoformat()] is True


# ---------------------------------------------------------------------------
# Releasing the time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_makes_the_slot_available_again(db, clinic_with_slots):
    """With a stored flag this needed the cancellation path to remember. Derived,
    it follows from the row it already updated."""
    slot = clinic_with_slots["slots"][1]
    appointment = await _book(db, clinic_with_slots, slot)

    assert _by_start(await _listing(db, clinic_with_slots))[
        slot.start_time.isoformat()
    ] is True

    await _cancel(db, appointment)

    assert _by_start(await _listing(db, clinic_with_slots))[
        slot.start_time.isoformat()
    ] is False


@pytest.mark.asyncio
async def test_rescheduling_moves_availability(db, clinic_with_slots):
    """Both ends have to change: the old slot frees and the new one blocks.

    A maintained flag has to remember both, and getting one right while missing
    the other is the classic form of this bug.
    """
    first, second, _ = clinic_with_slots["slots"]
    appointment = await _book(db, clinic_with_slots, first)

    appointment.scheduled_at = second.start_time
    appointment.time_range = Range(second.start_time, second.end_time)
    await db.flush()

    availability = _by_start(await _listing(db, clinic_with_slots))

    assert availability[first.start_time.isoformat()] is False, (
        "the vacated slot was not released"
    )
    assert availability[second.start_time.isoformat()] is True, (
        "the new slot was not taken"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, still_blocks",
    [
        (AppointmentStatus.PENDING, True),
        (AppointmentStatus.CONFIRMED, True),
        (AppointmentStatus.CANCELLED, False),
    ],
)
async def test_availability_follows_the_constraints_status_set(
    db, clinic_with_slots, status, still_blocks
):
    """Availability mirrors the exclusion constraint's WHERE clause. If these
    two sets diverge, the list starts promising times the database refuses."""
    slot = clinic_with_slots["slots"][2]
    await _book(db, clinic_with_slots, slot, status=status)

    availability = _by_start(await _listing(db, clinic_with_slots))

    assert availability[slot.start_time.isoformat()] is still_blocks


# ---------------------------------------------------------------------------
# only_available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_available_filters_booked_slots(db, clinic_with_slots):
    """It filtered nothing before, because the column it read was always
    false."""
    taken = clinic_with_slots["slots"][1]
    await _book(db, clinic_with_slots, taken)

    rows = await _listing(db, clinic_with_slots, only_available=True)

    starts = [row["start_time"] for row in rows]

    assert len(rows) == 2
    assert taken.start_time.isoformat() not in starts
    assert all(row["is_booked"] is False for row in rows)


@pytest.mark.asyncio
async def test_only_available_returns_nothing_when_all_are_taken(
    db, clinic_with_slots
):
    for slot in clinic_with_slots["slots"]:
        await _book(db, clinic_with_slots, slot)

    assert await _listing(db, clinic_with_slots, only_available=True) == []


@pytest.mark.asyncio
async def test_only_available_paginates_the_available_slots(
    db, clinic_with_slots
):
    """Filtering after pagination would return a short page instead of the
    next available slot, so the filter has to be in the query."""
    await _book(db, clinic_with_slots, clinic_with_slots["slots"][0])

    rows = await get_doctor_slots(
        db=db,
        doctor_id=clinic_with_slots["doctor"].id,
        start_date=clinic_with_slots["date"],
        days=1,
        only_available=True,
        limit=1,
        offset=0,
    )

    assert len(rows) == 1
    assert rows[0]["start_time"] == (
        clinic_with_slots["slots"][1].start_time.isoformat()
    )


# ---------------------------------------------------------------------------
# The assistant's recommendation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_earliest_slot_skips_an_occupied_slot(db, clinic_with_slots):
    """The worst version of the bug: telling a patient the earliest opening is
    a time somebody else already has."""
    first, second, _ = clinic_with_slots["slots"]
    await _book(db, clinic_with_slots, first)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=clinic_with_slots["clinic"].id, limit=5
    )

    starts = [row["start_time"] for row in results]

    assert first.start_time.isoformat() not in starts, (
        "recommended an occupied slot"
    )
    assert second.start_time.isoformat() in starts


@pytest.mark.asyncio
async def test_earliest_slot_recommends_nothing_when_fully_booked(
    db, clinic_with_slots
):
    for slot in clinic_with_slots["slots"]:
        await _book(db, clinic_with_slots, slot)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=clinic_with_slots["clinic"].id, limit=5
    )

    assert results == []


@pytest.mark.asyncio
async def test_earliest_slot_offers_a_cancelled_slot_again(
    db, clinic_with_slots
):
    first = clinic_with_slots["slots"][0]
    appointment = await _book(db, clinic_with_slots, first)
    await db.commit()

    await _cancel(db, appointment)
    await db.commit()

    results = await find_earliest_available_doctor(
        db, clinic_id=clinic_with_slots["clinic"].id, limit=5
    )

    assert first.start_time.isoformat() in [
        row["start_time"] for row in results
    ]


# ---------------------------------------------------------------------------
# Utilisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_utilisation_counts_a_completed_appointment(
    db, clinic_with_slots
):
    """Why utilisation needs a different status set from availability.

    Measured with the availability set, a completed consultation counts as
    unused — and since every past appointment ends up COMPLETED or NO_SHOW,
    the figure was structurally zero.
    """
    from app.services.admin_analytics_service import (
        get_doctor_utilization,
    )

    await _book(
        db, clinic_with_slots, clinic_with_slots["slots"][0],
        status=AppointmentStatus.COMPLETED,
    )

    result = await get_doctor_utilization(
        db=db,
        clinic_id=clinic_with_slots["clinic"].id,
        doctor_id=clinic_with_slots["doctor"].id,
    )

    assert result["utilization"] == pytest.approx(1 / 3, abs=0.001)


@pytest.mark.asyncio
async def test_utilisation_counts_a_no_show(db, clinic_with_slots):
    """Reserved and wasted is still time the doctor could not sell."""
    from app.services.admin_analytics_service import get_doctor_utilization

    await _book(
        db, clinic_with_slots, clinic_with_slots["slots"][0],
        status=AppointmentStatus.NO_SHOW,
    )

    result = await get_doctor_utilization(
        db=db,
        clinic_id=clinic_with_slots["clinic"].id,
        doctor_id=clinic_with_slots["doctor"].id,
    )

    assert result["utilization"] > 0


@pytest.mark.asyncio
async def test_utilisation_ignores_a_cancelled_appointment(
    db, clinic_with_slots
):
    from app.services.admin_analytics_service import get_doctor_utilization

    await _book(
        db, clinic_with_slots, clinic_with_slots["slots"][0],
        status=AppointmentStatus.CANCELLED,
    )

    result = await get_doctor_utilization(
        db=db,
        clinic_id=clinic_with_slots["clinic"].id,
        doctor_id=clinic_with_slots["doctor"].id,
    )

    assert result["utilization"] == 0


# ---------------------------------------------------------------------------
# There is no second source of truth
# ---------------------------------------------------------------------------


def test_the_slot_model_stores_no_booking_state():
    """The property that stops this recurring.

    Every other test here would pass against a stored flag that happened to be
    maintained correctly. This one fails the moment somebody re-adds one, which
    is the point: the old column was not wrong because it held a wrong value,
    it was wrong because it could.
    """
    columns = {column.key for column in inspect(DoctorSlot).columns}

    assert "is_booked" not in columns
    assert not any(
        "book" in name.lower() for name in columns
    ), f"doctor_slots has booking state again: {sorted(columns)}"


@pytest.mark.asyncio
async def test_the_column_is_gone_from_the_database_too(db):
    """Not just the model — a column left behind can still be read by raw SQL
    or resurrected by a careless autogenerate."""
    found = await db.scalar(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'doctor_slots' AND column_name = 'is_booked'"
        )
    )

    assert found == 0


def test_occupancy_is_defined_in_exactly_one_place():
    """Availability, the earliest-slot filter and utilisation all read from
    app/domain/scheduling/occupancy.py. Three services with three private
    copies of "what counts as booked" is the same defect in a new shape."""
    import ast
    from pathlib import Path

    services = Path(__file__).parent.parent.parent / "app" / "services"

    offenders = []

    for path in services.glob("*.py"):
        tree = ast.parse(path.read_text())

        mentions_slots = "DoctorSlot" in path.read_text()

        if not mentions_slots:
            continue

        # Any service reasoning about slot occupancy must import the predicate
        # rather than assemble its own status list.
        source = path.read_text()

        if "AppointmentStatus.CONFIRMED" in source and "DoctorSlot" in source:
            if "occupancy import" not in source:
                offenders.append(path.name)

    assert not offenders, (
        f"these services build their own notion of a booked slot: {offenders}"
    )
