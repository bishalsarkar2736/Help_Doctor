"""Booking on behalf of a patient, and which clinic that may happen in.

WHAT THIS COVERS
AppointmentCreate carries an optional patient_id, honoured only for a
RECEPTIONIST or ADMIN — the front desk booking for the person standing at it.
The route enforces that role gate and nothing else, and the branch had no test
of any kind: no test in the suite passes patient_id to create-appointment.

THE GAP
`book_appointment(db, patient, doctor_id, scheduled_at)` never received the
ACTOR, only the patient being booked. The appointment's tenant is taken from
the doctor:

    appointment = Appointment(..., clinic_id=doctor.clinic_id)

so a receptionist at clinic A naming clinic B's doctor wrote an appointment
into clinic B's schedule — a cross-tenant write, and one that also puts a
patient into another clinic's live queue.

WHY THIS MATTERS MORE THAN IT LOOKS
Access to a patient's record is derived from appointments: `search_patients`
scopes to "at least one appointment at clinic_id", and get_patient_record now
uses the same rule. Booking is therefore the act that CREATES the relationship
those checks depend on. A booking endpoint that accepts any doctor in any
clinic can manufacture that relationship, which is why the clinic check belongs
here and not only on the read side.

WHAT IS DELIBERATELY STILL ALLOWED
A patient booking for THEMSELVES may name a doctor at any clinic. Patients are
global identities — test_a_patient_is_not_bound_to_a_clinic pins that — and the
public directory exists so they can find and book a clinic they have never
visited. Constraining self-booking to a clinic the patient already belongs to
would break the product's front door, so the rule applies only when someone is
acting on another person's behalf.
"""

from datetime import datetime, timedelta

import pytest

from app.core.time import UTC
from app.models.doctor_availability import DoctorAvailability
from app.services.appointment_service import book_appointment
from app.try_except.exceptions import ForbiddenError
from tests.conftest import valid_slot

from datetime import time as dtime

import pytest_asyncio


def _slot(days: int = 1) -> datetime:
    return valid_slot(datetime.now(UTC) + timedelta(days=days))


@pytest_asyncio.fixture
async def other_clinic_doctor_availability(db, other_clinic_doctor):
    """Clinic B's doctor, bookable — so the allow-case below fails on
    authorization if it fails at all, never on a missing slot."""

    for day in range(7):
        db.add(
            DoctorAvailability(
                doctor_id=other_clinic_doctor["doctor"].id,
                day_of_week=day,
                start_time=dtime(0, 0),
                end_time=dtime(23, 59),
                is_available=True,
            )
        )

    await db.flush()


# ---------------------------------------------------------------------------
# Acting on behalf: the actor's clinic bounds the booking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_receptionist_cannot_book_with_another_clinics_doctor(
    db, patient_user, auth_receptionist, other_clinic_doctor
):
    with pytest.raises(ForbiddenError):
        await book_appointment(
            db=db,
            patient=patient_user,
            doctor_id=other_clinic_doctor["doctor"].id,
            scheduled_at=_slot(),
            booked_by=auth_receptionist["user"],
        )


@pytest.mark.asyncio
async def test_an_admin_cannot_book_with_another_clinics_doctor(
    db, patient_user, auth_admin, other_clinic_doctor
):
    with pytest.raises(ForbiddenError):
        await book_appointment(
            db=db,
            patient=patient_user,
            doctor_id=other_clinic_doctor["doctor"].id,
            scheduled_at=_slot(),
            booked_by=auth_admin["user"],
        )


@pytest.mark.asyncio
async def test_authorization_is_refused_before_any_slot_is_taken(
    db, patient_user, auth_receptionist, other_clinic_doctor,
    other_clinic_doctor_availability
):
    """The refusal must not depend on the slot being unavailable.

    With clinic B's doctor fully bookable, a check placed after availability
    validation would let this through. Authorization comes first.
    """

    with pytest.raises(ForbiddenError):
        await book_appointment(
            db=db,
            patient=patient_user,
            doctor_id=other_clinic_doctor["doctor"].id,
            scheduled_at=_slot(),
            booked_by=auth_receptionist["user"],
        )


# ---------------------------------------------------------------------------
# The paired allow-cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_receptionist_can_book_with_their_own_clinics_doctor(
    db, patient_user, auth_receptionist, doctor, doctor_availability
):
    """The job the front desk actually does."""

    appointment = await book_appointment(
        db=db,
        patient=patient_user,
        doctor_id=doctor.id,
        scheduled_at=_slot(),
        booked_by=auth_receptionist["user"],
    )

    assert appointment.patient_id == patient_user.id
    assert appointment.clinic_id == doctor.clinic_id


@pytest.mark.asyncio
async def test_a_patient_may_still_book_themselves_at_any_clinic(
    db, patient_user, other_clinic_doctor, other_clinic_doctor_availability
):
    """Self-booking is unchanged. Patients are global identities and the public
    directory exists for exactly this — a patient finding a clinic they have
    never visited."""

    appointment = await book_appointment(
        db=db,
        patient=patient_user,
        doctor_id=other_clinic_doctor["doctor"].id,
        scheduled_at=_slot(),
        booked_by=patient_user,
    )

    assert appointment.clinic_id == other_clinic_doctor["doctor"].clinic_id


@pytest.mark.asyncio
async def test_an_unattributed_booking_still_works(
    db, patient_user, doctor, doctor_availability
):
    """booked_by is optional: eighteen existing call sites use the positional
    signature, and the scheduler books without an acting user at all."""

    appointment = await book_appointment(
        db=db,
        patient=patient_user,
        doctor_id=doctor.id,
        scheduled_at=_slot(),
    )

    assert appointment.patient_id == patient_user.id
