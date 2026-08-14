"""GET /appointments/queue?doctor_id=… — the front desk's view of a queue.

WHY THE ENDPOINT EXISTS
Reception can put a patient into a doctor's queue (move-to-waiting) and could
not see any queue afterwards. The only queue views were
GET /appointments/doctor/queue and /doctor/queue/stats, both DOCTOR-only and
both self-derived — they resolve the doctor from the caller's own profile, so
there was no way to name a doctor at all. A clinic with three doctors had three
queues and no way for the desk to look at any of them.

WHERE THE TENANT CHECK HAS TO LIVE
waiting_queue_service takes a doctor_id and trusts it. Every function in it —
get_waiting_patients, get_queue_length, get_doctor_queue_summary — filters on
doctor_id and status and contains no clinic predicate at all. That was safe
only while no endpoint let a caller supply the id.

This endpoint does, so the API boundary must establish the tenant relationship
before delegating:

    caller's clinic  →  doctor_id  →  Doctor.clinic_id == caller's clinic
                                   →  get_doctor_queue_summary(doctor_id=…)

The tests below assert that order. A rule enforced inside the service would be
a different design; this file pins the one that exists.

A note on the caller's clinic: it is NOT simply user.clinic_id. Doctors carry
their clinic on the Doctor row rather than the user, which is why a doctor
calling this must resolve through that row — the same asymmetry
_searcher_clinic_id documents on the patient search.
"""

from datetime import datetime, timedelta

import pytest

from app.core.time import UTC
from app.models.appointment import AppointmentStatus
from tests.conftest import valid_slot

QUEUE = "/appointments/queue"


async def _waiting(appointment_factory, patient_id, doctor_id, days=1):
    return await appointment_factory(
        patient_id=patient_id,
        doctor_id=doctor_id,
        status=AppointmentStatus.WAITING,
        scheduled_at=valid_slot(datetime.now(UTC) + timedelta(days=days)),
    )


# ---------------------------------------------------------------------------
# The receptionist's own clinic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receptionist_can_view_a_doctor_in_their_own_clinic(
    client, auth_receptionist, doctor, patient_user, appointment_factory
):
    await _waiting(appointment_factory, patient_user.id, doctor.id)

    res = await client.get(
        QUEUE, params={"doctor_id": doctor.id},
        headers=auth_receptionist["headers"],
    )
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["queue_length"] == 1
    assert [p["patient_id"] for p in body["waiting"]] == [patient_user.id]


@pytest.mark.asyncio
async def test_receptionist_cannot_view_another_clinics_doctor(
    client, auth_receptionist, other_clinic_doctor, other_clinic_patient,
    appointment_factory
):
    """THE POINT OF THE ENDPOINT'S AUTHORIZATION.

    The doctor_id is well-formed and the doctor exists; only the clinic
    differs. Passing it straight to waiting_queue_service would return the
    other clinic's queue, patient names included.
    """

    await _waiting(
        appointment_factory,
        other_clinic_patient.id,
        other_clinic_doctor["doctor"].id,
    )

    res = await client.get(
        QUEUE, params={"doctor_id": other_clinic_doctor["doctor"].id},
        headers=auth_receptionist["headers"],
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_no_patient_name_leaks_in_the_refused_response(
    client, auth_receptionist, other_clinic_doctor, other_clinic_patient,
    appointment_factory
):
    """Asserted on the body, not the status code."""

    await _waiting(
        appointment_factory,
        other_clinic_patient.id,
        other_clinic_doctor["doctor"].id,
    )

    res = await client.get(
        QUEUE, params={"doctor_id": other_clinic_doctor["doctor"].id},
        headers=auth_receptionist["headers"],
    )

    assert "patient_name" not in res.text
    assert "waiting" not in res.text


@pytest.mark.asyncio
async def test_an_unknown_doctor_is_not_found(client, auth_receptionist):
    res = await client.get(
        QUEUE, params={"doctor_id": 999_999},
        headers=auth_receptionist["headers"],
    )
    assert res.status_code in (403, 404), res.text


# ---------------------------------------------------------------------------
# Doctor A vs Doctor B — independent queues inside one clinic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_doctors_in_one_clinic_have_independent_queues(
    client, auth_receptionist, doctor, another_doctor, patient_user,
    another_patient_user, appointment_factory
):
    """The multi-doctor claim, verified rather than assumed.

    The queue is derived from appointment rows, so 'independent' means the
    filter is doctor_id — one doctor's waiting patient must not appear in the
    other's queue.
    """

    await _waiting(appointment_factory, patient_user.id, doctor.id, days=1)
    await _waiting(
        appointment_factory, another_patient_user.id, another_doctor.id, days=2
    )

    first = await client.get(
        QUEUE, params={"doctor_id": doctor.id},
        headers=auth_receptionist["headers"],
    )
    second = await client.get(
        QUEUE, params={"doctor_id": another_doctor.id},
        headers=auth_receptionist["headers"],
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    assert [p["patient_id"] for p in first.json()["waiting"]] == [
        patient_user.id
    ]
    assert [p["patient_id"] for p in second.json()["waiting"]] == [
        another_patient_user.id
    ]

    assert first.json()["queue_length"] == 1
    assert second.json()["queue_length"] == 1


@pytest.mark.asyncio
async def test_the_queue_is_ordered_by_arrival_not_appointment_time(
    client, db, auth_receptionist, doctor, patient_user, another_patient_user,
    appointment_factory
):
    """FIFO on waiting_started_at, which is what the desk actually promises:
    whoever was put in the queue first is seen first."""

    later_appointment = await _waiting(
        appointment_factory, patient_user.id, doctor.id, days=2
    )
    earlier_appointment = await _waiting(
        appointment_factory, another_patient_user.id, doctor.id, days=1
    )

    now = datetime.now(UTC)
    later_appointment.waiting_started_at = now - timedelta(minutes=30)
    earlier_appointment.waiting_started_at = now - timedelta(minutes=5)
    await db.flush()

    res = await client.get(
        QUEUE, params={"doctor_id": doctor.id},
        headers=auth_receptionist["headers"],
    )
    assert res.status_code == 200, res.text

    # The one waiting longest comes first, regardless of scheduled_at.
    assert [p["patient_id"] for p in res.json()["waiting"]] == [
        patient_user.id,
        another_patient_user.id,
    ]


# ---------------------------------------------------------------------------
# The other roles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_doctor_can_view_a_queue_in_their_own_clinic(
    client, auth_doctor, patient_user, appointment_factory
):
    """A doctor's clinic comes from their Doctor row, not user.clinic_id —
    resolving it the wrong way would deny every doctor.

    Uses auth_doctor's own Doctor row rather than also requesting the `doctor`
    fixture: both build a doctor user and the two collide on the email unique
    index.
    """

    their_doctor = auth_doctor["doctor"]

    await _waiting(appointment_factory, patient_user.id, their_doctor.id)

    res = await client.get(
        QUEUE, params={"doctor_id": their_doctor.id},
        headers=auth_doctor["headers"],
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_an_admin_can_view_a_queue_in_their_own_clinic(
    client, auth_admin, doctor, patient_user, appointment_factory
):
    await _waiting(appointment_factory, patient_user.id, doctor.id)

    res = await client.get(
        QUEUE, params={"doctor_id": doctor.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_a_patient_cannot_view_a_queue(
    client, auth_patient, doctor
):
    res = await client.get(
        QUEUE, params={"doctor_id": doctor.id},
        headers=auth_patient["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_doctor_id_is_required(client, auth_receptionist):
    res = await client.get(QUEUE, headers=auth_receptionist["headers"])
    assert res.status_code == 422, res.text
