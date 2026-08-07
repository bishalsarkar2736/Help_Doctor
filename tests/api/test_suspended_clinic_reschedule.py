"""A suspended clinic stops taking time, by every route into it.

The clinic-status check lived inline in the booking path, so booking against a
suspended clinic returned 409 while MOVING an existing appointment into a new
slot there succeeded. Rescheduling is a new booking in everything but name: it
claims a slot that was previously free.

Each path read as correct on its own, which is why the gap survived — the
inconsistency only exists between them. The check now lives in one helper that
all three call.

WHAT STAYS ALLOWED, DELIBERATELY
Existing appointments are not cancelled, hidden or modified, and cancelling one
is still permitted. Suspension is usually a billing matter between the platform
and the clinic; trapping a patient in an appointment they want out of would
make them pay for it.
"""

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy.dialects.postgresql import Range

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_availability import DoctorAvailability
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.security.jwt import create_access_token


def _next_slot(days_ahead: int, hour: int) -> datetime:
    """A future time on an exact 20-minute boundary.

    Slot alignment is validated before availability, so an unaligned time makes
    a test fail for a reason that has nothing to do with what it is testing.
    """
    target = utc_now() + timedelta(days=days_ahead)
    return target.replace(hour=hour, minute=0, second=0, microsecond=0)


@pytest.fixture
async def bookable_clinic(db):
    """A clinic a booking would genuinely succeed against.

    The doctor is available every weekday, all day, so when a reschedule is
    refused it is the clinic's status doing it and not an availability rule —
    the difference between testing the gate and testing the calendar.
    """
    clinic = Clinic(
        name="Suspendable Clinic", status=ClinicStatus.ACTIVE, timezone="UTC"
    )
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email="susp-doc@example.com", full_name="Dr Suspendable",
        hashed_password="x", role=UserRole.DOCTOR, is_active=True,
        clinic_id=clinic.id,
    )
    db.add(doctor_user)
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=5, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()

    for weekday in range(7):
        db.add(DoctorAvailability(
            doctor_id=doctor.id, day_of_week=weekday,
            start_time=time(0, 0), end_time=time(23, 59), is_available=True,
        ))

    patient_user = User(
        email="susp-patient@example.com", full_name="Suspendable Patient",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(patient_user)
    await db.flush()

    db.add(Patient(
        user_id=patient_user.id, phone="+8801766000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    booked_at = _next_slot(2, 10)
    appointment = Appointment(
        patient_id=patient_user.id, doctor_id=doctor.id, clinic_id=clinic.id,
        scheduled_at=booked_at, status=AppointmentStatus.CONFIRMED,
        time_range=Range(booked_at, booked_at + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()
    await db.commit()

    def _headers(user, role):
        token = create_access_token(data={"sub": str(user.id), "role": role})
        return {"Authorization": f"Bearer {token}"}

    return {
        "clinic": clinic,
        "doctor": doctor,
        "appointment": appointment,
        "patient_headers": _headers(patient_user, UserRole.PATIENT.value),
        "doctor_headers": _headers(doctor_user, UserRole.DOCTOR.value),
    }


async def _suspend(db, clinic):
    clinic.status = ClinicStatus.SUSPENDED
    await db.commit()


async def _reschedule_as_patient(client, ctx, when):
    return await client.post(
        f"/appointments/{ctx['appointment'].id}/reschedule-by-patient",
        params={"new_datetime": when.isoformat()},
        headers=ctx["patient_headers"],
    )


async def _reschedule_as_doctor(client, ctx, when):
    return await client.post(
        f"/appointments/{ctx['appointment'].id}/reschedule-by-doctor",
        params={"new_datetime": when.isoformat()},
        headers=ctx["doctor_headers"],
    )


# ---------------------------------------------------------------------------
# The fixture is real: these succeed while the clinic is active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_patient_can_reschedule_while_the_clinic_is_active(
    client, bookable_clinic
):
    """Without this, the refusals below prove nothing — a reschedule that was
    never going to work cannot demonstrate that suspension stopped it."""
    res = await _reschedule_as_patient(client, bookable_clinic, _next_slot(3, 11))

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_a_doctor_can_reschedule_while_the_clinic_is_active(
    client, bookable_clinic
):
    res = await _reschedule_as_doctor(client, bookable_clinic, _next_slot(4, 12))

    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# Suspension stops both
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_patient_cannot_reschedule_into_a_suspended_clinic(
    client, db, bookable_clinic
):
    await _suspend(db, bookable_clinic["clinic"])

    res = await _reschedule_as_patient(client, bookable_clinic, _next_slot(3, 11))

    assert res.status_code == 409, res.text
    assert "temporarily unavailable" in res.text


@pytest.mark.asyncio
async def test_a_doctor_cannot_reschedule_into_a_suspended_clinic(
    client, db, bookable_clinic
):
    """The clinic's own staff are stopped too — a suspended clinic is not open
    for the people who work there to keep booking its time."""
    await _suspend(db, bookable_clinic["clinic"])

    res = await _reschedule_as_doctor(client, bookable_clinic, _next_slot(4, 12))

    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_a_deleted_clinic_stops_rescheduling_too(client, db, bookable_clinic):
    """is_public covers DELETED as well; suspension is not the only offline
    state."""
    bookable_clinic["clinic"].status = ClinicStatus.DELETED
    await db.commit()

    res = await _reschedule_as_patient(client, bookable_clinic, _next_slot(3, 11))

    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_the_appointment_is_left_where_it_was(client, db, bookable_clinic):
    """A refusal must not half-apply.

    The status check sits before the write, so the appointment keeps its
    original time rather than being moved and then rejected.
    """
    original = bookable_clinic["appointment"].scheduled_at

    await _suspend(db, bookable_clinic["clinic"])
    await _reschedule_as_patient(client, bookable_clinic, _next_slot(3, 11))

    await db.refresh(bookable_clinic["appointment"])

    assert bookable_clinic["appointment"].scheduled_at == original
    assert bookable_clinic["appointment"].status == AppointmentStatus.CONFIRMED


# ---------------------------------------------------------------------------
# What suspension must NOT break
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_still_works_at_a_suspended_clinic(
    client, db, bookable_clinic
):
    """Deliberate. Suspension is usually a billing matter between the platform
    and the clinic, and trapping a patient in an appointment they want out of
    would make the patient pay for it."""
    await _suspend(db, bookable_clinic["clinic"])

    res = await client.post(
        f"/appointments/{bookable_clinic['appointment'].id}/cancel-by-patient",
        json={"reason": "changed my mind"},
        headers=bookable_clinic["patient_headers"],
    )

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_the_patient_can_still_see_the_appointment(
    client, db, bookable_clinic
):
    """Not hidden, not cancelled — the record stays visible to its owner."""
    await _suspend(db, bookable_clinic["clinic"])

    res = await client.get(
        "/appointments/own", headers=bookable_clinic["patient_headers"]
    )

    assert res.status_code == 200, res.text
    assert any(
        a["id"] == bookable_clinic["appointment"].id for a in res.json()
    )


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clinic_status_is_not_revealed_before_ownership_is_checked(
    client, db, bookable_clinic
):
    """A stranger must not learn a clinic is suspended by poking at somebody
    else's appointment. Ownership is decided first, so this is 403 rather than
    the 409 the owner would get."""
    intruder = User(
        email="intruder@example.com", full_name="Intruder", hashed_password="x",
        role=UserRole.PATIENT, is_active=True,
    )
    db.add(intruder)
    await db.flush()

    db.add(Patient(
        user_id=intruder.id, phone="+8801766000999", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await _suspend(db, bookable_clinic["clinic"])

    token = create_access_token(
        data={"sub": str(intruder.id), "role": UserRole.PATIENT.value}
    )

    res = await client.post(
        f"/appointments/{bookable_clinic['appointment'].id}/reschedule-by-patient",
        params={"new_datetime": _next_slot(3, 11).isoformat()},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 403, res.text
    assert "temporarily unavailable" not in res.text


@pytest.mark.asyncio
async def test_booking_is_still_blocked(client, db, bookable_clinic):
    """The behaviour that already worked, kept working while the check moved
    into a shared helper."""
    await _suspend(db, bookable_clinic["clinic"])

    res = await client.post(
        "/appointments/",
        json={
            "doctor_id": bookable_clinic["doctor"].id,
            "scheduled_at": _next_slot(5, 9).isoformat(),
        },
        headers=bookable_clinic["patient_headers"],
    )

    assert res.status_code == 409, res.text
