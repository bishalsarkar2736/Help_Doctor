from datetime import datetime, timedelta

import pytest

from app.core.time import UTC
from app.models.appointment import Appointment
from tests.conftest import valid_slot


@pytest.mark.asyncio
async def test_receptionist_books_on_behalf_of_patient(
    client, db, patient_user, doctor, doctor_availability, auth_receptionist
):
    slot = valid_slot(datetime.now(UTC) + timedelta(days=1))

    res = await client.post(
        "/appointments/",
        json={
            "doctor_id": doctor.id,
            "scheduled_at": slot.isoformat(),
            "patient_id": patient_user.id,
        },
        headers=auth_receptionist["headers"],
    )
    assert res.status_code == 200, res.text

    appt_id = res.json()["appointment_id"]
    appt = await db.get(Appointment, appt_id)
    # The appointment belongs to the patient, NOT the receptionist.
    assert appt.patient_id == patient_user.id
    assert appt.patient_id != auth_receptionist["user"].id


@pytest.mark.asyncio
async def test_receptionist_bogus_patient_id_404(
    client, doctor, doctor_availability, auth_receptionist
):
    slot = valid_slot(datetime.now(UTC) + timedelta(days=1))

    res = await client.post(
        "/appointments/",
        json={
            "doctor_id": doctor.id,
            "scheduled_at": slot.isoformat(),
            "patient_id": 999999,
        },
        headers=auth_receptionist["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_patient_cannot_book_for_another_patient(
    client, doctor, doctor_availability, auth_patient, patient_user
):
    slot = valid_slot(datetime.now(UTC) + timedelta(days=1))

    res = await client.post(
        "/appointments/",
        json={
            "doctor_id": doctor.id,
            "scheduled_at": slot.isoformat(),
            "patient_id": patient_user.id,  # a different patient
        },
        headers=auth_patient["headers"],
    )
    assert res.status_code == 403, res.text
