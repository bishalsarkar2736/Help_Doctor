import pytest
from sqlalchemy import func, select

from app.models.appointment import AppointmentStatus
from app.models.doctor_rating import DoctorRating


async def _completed_appointment(appointment_factory, patient, doctor):
    return await appointment_factory(
        patient_id=patient["user"].id,
        doctor_id=doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )


@pytest.mark.asyncio
async def test_patient_can_rate_completed_appointment(
    client, auth_patient, auth_doctor, appointment_factory
):
    appointment = await _completed_appointment(
        appointment_factory, auth_patient, auth_doctor
    )

    response = await client.post(
        f"/appointments/{appointment.id}/rating",
        json={"stars": 5, "comment": "Explained everything clearly."},
        headers=auth_patient["headers"],
    )

    assert response.status_code == 200
    data = response.json()
    assert data["stars"] == 5
    assert data["comment"] == "Explained everything clearly."
    assert data["editable"] is True


@pytest.mark.asyncio
async def test_cannot_rate_appointment_that_is_not_completed(
    client, auth_patient, auth_doctor, appointment_factory
):
    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    response = await client.post(
        f"/appointments/{appointment.id}/rating",
        json={"stars": 5},
        headers=auth_patient["headers"],
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cannot_rate_another_patients_appointment(
    client,
    auth_patient,
    auth_doctor,
    another_patient_user,
    appointment_factory,
):
    """The core anti-brigading rule: no visit, no rating."""

    appointment = await appointment_factory(
        patient_id=another_patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    response = await client.post(
        f"/appointments/{appointment.id}/rating",
        json={"stars": 1},
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_rating_twice_edits_instead_of_duplicating(
    client, db, auth_patient, auth_doctor, appointment_factory
):
    appointment = await _completed_appointment(
        appointment_factory, auth_patient, auth_doctor
    )

    for stars in (2, 4):
        response = await client.post(
            f"/appointments/{appointment.id}/rating",
            json={"stars": stars},
            headers=auth_patient["headers"],
        )
        assert response.status_code == 200

    assert response.json()["stars"] == 4

    total = await db.scalar(
        select(func.count())
        .select_from(DoctorRating)
        .where(DoctorRating.appointment_id == appointment.id)
    )
    assert total == 1


@pytest.mark.asyncio
async def test_stars_outside_one_to_five_rejected(
    client, auth_patient, auth_doctor, appointment_factory
):
    appointment = await _completed_appointment(
        appointment_factory, auth_patient, auth_doctor
    )

    response = await client.post(
        f"/appointments/{appointment.id}/rating",
        json={"stars": 6},
        headers=auth_patient["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_summary_aggregates_and_hides_comments(
    client, auth_patient, auth_doctor, appointment_factory
):
    appointment = await _completed_appointment(
        appointment_factory, auth_patient, auth_doctor
    )

    secret = "Kept away from the public page"
    await client.post(
        f"/appointments/{appointment.id}/rating",
        json={"stars": 4, "comment": secret},
        headers=auth_patient["headers"],
    )

    doctor_id = auth_doctor["doctor"].id
    response = await client.get(f"/doctors/{doctor_id}/rating-summary")

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 1
    assert data["average"] == 4.0
    assert data["distribution"]["4"] == 1
    # The privacy guarantee: no free text anywhere in the public payload.
    assert secret not in response.text


@pytest.mark.asyncio
async def test_summary_is_empty_for_unrated_doctor(client, auth_doctor):
    doctor_id = auth_doctor["doctor"].id
    response = await client.get(f"/doctors/{doctor_id}/rating-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["average"] is None


@pytest.mark.asyncio
async def test_admin_sees_comment_text(
    client,
    auth_patient,
    auth_doctor,
    auth_admin,
    default_clinic,
    appointment_factory,
):
    appointment = await _completed_appointment(
        appointment_factory, auth_patient, auth_doctor
    )

    comment = "Waiting room was very slow."
    await client.post(
        f"/appointments/{appointment.id}/rating",
        json={"stars": 3, "comment": comment},
        headers=auth_patient["headers"],
    )

    doctor_id = auth_doctor["doctor"].id
    response = await client.get(
        f"/admin/doctors/{doctor_id}/ratings",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["comment"] == comment
    assert body[0]["stars"] == 3


@pytest.mark.asyncio
async def test_doctor_cannot_read_own_rating_comments(
    client, auth_doctor, default_clinic
):
    """Comments are admin-only — a doctor reading them de-anonymises patients."""

    doctor_id = auth_doctor["doctor"].id
    response = await client.get(
        f"/admin/doctors/{doctor_id}/ratings",
        params={"clinic_id": default_clinic.id},
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reading_own_rating_before_rating_returns_404(
    client, auth_patient, auth_doctor, appointment_factory
):
    appointment = await _completed_appointment(
        appointment_factory, auth_patient, auth_doctor
    )

    response = await client.get(
        f"/appointments/{appointment.id}/rating",
        headers=auth_patient["headers"],
    )

    assert response.status_code == 404
