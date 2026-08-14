"""What reception actually does, and where it stops.

Check-in and move-to-waiting are the front desk's two operations, and both
admitted RECEPTIONIST long before this file existed — but every test of them
was written as a DOCTOR. That is the gap this closes: the role that performs
these steps in practice had no test performing them.

The boundary matters as much as the capability. Reception moves a patient
towards the doctor and stops there: starting a consultation, completing one and
writing a prescription are clinical acts, and the tests below assert reception
is refused all three rather than trusting the route decorators to stay as they
are.

Clinic scoping is asserted at the HTTP boundary rather than on the service, so
these fail if the route ever stops loading through get_appointment_by_id — the
function that carries the clinic check for both operations.
"""

import pytest

from app.models.appointment import AppointmentStatus


@pytest.fixture
def headers(auth_receptionist):
    return auth_receptionist["headers"]


async def _appointment(appointment_factory, patient_user, doctor, status):
    return await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=status,
    )


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receptionist_can_check_in_their_own_clinics_patient(
    client, db, headers, appointment_factory, patient_user, doctor
):
    appointment = await _appointment(
        appointment_factory, patient_user, doctor, AppointmentStatus.CONFIRMED
    )

    res = await client.post(
        f"/appointments/{appointment.id}/check-in", headers=headers
    )
    assert res.status_code == 200, res.text

    await db.refresh(appointment)
    assert appointment.status == AppointmentStatus.CHECKED_IN
    assert appointment.checked_in_at is not None, (
        "checked_in_at is what the queue and the dashboards order by"
    )


@pytest.mark.asyncio
async def test_receptionist_cannot_check_in_another_clinics_patient(
    client, headers, appointment_factory, other_clinic_patient,
    other_clinic_doctor
):
    appointment = await appointment_factory(
        patient_id=other_clinic_patient.id,
        doctor_id=other_clinic_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    res = await client.post(
        f"/appointments/{appointment.id}/check-in", headers=headers
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_check_in_respects_the_appointment_state_machine(
    client, headers, appointment_factory, patient_user, doctor
):
    """PENDING has no CHECKED_IN transition: an unconfirmed patient cannot be
    admitted to the queue."""

    appointment = await _appointment(
        appointment_factory, patient_user, doctor, AppointmentStatus.PENDING
    )

    res = await client.post(
        f"/appointments/{appointment.id}/check-in", headers=headers
    )
    assert res.status_code == 400, res.text


# ---------------------------------------------------------------------------
# Move to waiting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receptionist_can_move_a_checked_in_patient_to_waiting(
    client, db, headers, appointment_factory, patient_user, doctor
):
    appointment = await _appointment(
        appointment_factory, patient_user, doctor, AppointmentStatus.CHECKED_IN
    )

    res = await client.post(
        f"/appointments/{appointment.id}/move-to-waiting", headers=headers
    )
    assert res.status_code == 200, res.text

    await db.refresh(appointment)
    assert appointment.status == AppointmentStatus.WAITING
    assert appointment.waiting_started_at is not None, (
        "waiting_started_at is the queue's FIFO ordering key"
    )


@pytest.mark.asyncio
async def test_receptionist_cannot_move_another_clinics_patient_to_waiting(
    client, headers, appointment_factory, other_clinic_patient,
    other_clinic_doctor
):
    appointment = await appointment_factory(
        patient_id=other_clinic_patient.id,
        doctor_id=other_clinic_doctor["doctor"].id,
        status=AppointmentStatus.CHECKED_IN,
    )

    res = await client.post(
        f"/appointments/{appointment.id}/move-to-waiting", headers=headers
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_a_patient_must_be_checked_in_before_waiting(
    client, headers, appointment_factory, patient_user, doctor
):
    appointment = await _appointment(
        appointment_factory, patient_user, doctor, AppointmentStatus.CONFIRMED
    )

    res = await client.post(
        f"/appointments/{appointment.id}/move-to-waiting", headers=headers
    )
    assert res.status_code == 400, res.text


# ---------------------------------------------------------------------------
# Where reception stops: clinical acts belong to the doctor
# ---------------------------------------------------------------------------


# The denial these two assert on is the ROLE GATE, named explicitly.
#
# A bare `status_code == 403` looked right and proved nothing: a receptionist
# has no Doctor row, so adding RECEPTIONIST to the route still returned 403 —
# from get_doctor_profile, several steps later. Mutation testing caught that
# the assertion could not tell the boundary from an unrelated failure.
#
# require_roles answers "Permission denied"; get_doctor_profile answers
# "Doctor profile not found". Asserting the former is what makes these tests
# about the permission boundary rather than about a missing profile.
ROLE_GATE_DENIAL = "Permission denied"


@pytest.mark.asyncio
async def test_receptionist_cannot_start_a_consultation(
    client, headers, appointment_factory, patient_user, doctor
):
    appointment = await _appointment(
        appointment_factory, patient_user, doctor, AppointmentStatus.WAITING
    )

    res = await client.post(
        f"/appointments/{appointment.id}/start-consultation", headers=headers
    )
    assert res.status_code == 403, res.text
    assert ROLE_GATE_DENIAL in res.text, (
        "refused, but not by the role gate — the route may now admit "
        f"RECEPTIONIST: {res.text}"
    )


@pytest.mark.asyncio
async def test_receptionist_cannot_complete_a_consultation(
    client, headers, appointment_factory, patient_user, doctor
):
    appointment = await _appointment(
        appointment_factory, patient_user, doctor,
        AppointmentStatus.IN_CONSULTATION,
    )

    res = await client.post(
        f"/appointments/{appointment.id}/complete-consultation", headers=headers
    )
    assert res.status_code == 403, res.text
    assert ROLE_GATE_DENIAL in res.text, (
        "refused, but not by the role gate — the route may now admit "
        f"RECEPTIONIST: {res.text}"
    )


@pytest.mark.asyncio
async def test_the_doctor_still_performs_the_clinical_steps(
    client, db, auth_doctor, appointment_factory, patient_user
):
    """The paired allow-case for the two refusals above: the steps reception
    cannot take are taken by somebody, so those tests cannot be satisfied by a
    route that is simply broken."""

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.WAITING,
    )

    start = await client.post(
        f"/appointments/{appointment.id}/start-consultation",
        headers=auth_doctor["headers"],
    )
    assert start.status_code == 200, start.text

    await db.refresh(appointment)
    assert appointment.status == AppointmentStatus.IN_CONSULTATION

    done = await client.post(
        f"/appointments/{appointment.id}/complete-consultation",
        headers=auth_doctor["headers"],
    )
    assert done.status_code == 200, done.text

    await db.refresh(appointment)
    assert appointment.status == AppointmentStatus.COMPLETED
