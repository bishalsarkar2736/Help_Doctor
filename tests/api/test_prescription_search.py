import pytest

from app.models.prescription import (
    PrescriptionStatus,
)
from app.models.appointment import (
    AppointmentStatus,
)


@pytest.mark.asyncio
async def test_admin_can_search_prescriptions(
    client,
    auth_admin,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):
    """
    Admin can search prescriptions.
    """

    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.ISSUED,
    )

    response = await client.get(
        "/prescriptions/search",
        params={
            "clinic_id": auth_doctor["doctor"].clinic_id,
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_doctor_can_search_prescriptions(
    client,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):
    """
    Doctor can search prescriptions.
    """

    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.ISSUED,
    )

    response = await client.get(
        "/prescriptions/search",
        params={
            "clinic_id": auth_doctor["doctor"].clinic_id,
        },
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_receptionist_can_search_prescriptions(
    client,
    auth_receptionist,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):
    """
    Receptionist can search prescriptions.
    """

    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.ISSUED,
    )

    response = await client.get(
        "/prescriptions/search",
        params={
            "clinic_id": auth_doctor["doctor"].clinic_id,
        },
        headers=auth_receptionist["headers"],
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_patient_cannot_search_prescriptions(
    client,
    auth_patient,
    auth_doctor,
):
    """
    Patients cannot search prescriptions.
    """

    response = await client.get(
        "/prescriptions/search",
        params={
            "clinic_id": auth_doctor["doctor"].clinic_id,
        },
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_search_by_medication(
    client,
    auth_admin,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):
    """
    Search prescriptions by medication name.
    """

    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.ISSUED,
    )

    response = await client.get(
        "/prescriptions/search",
        params={
            "clinic_id": auth_doctor["doctor"].clinic_id,
            "medication": "Napa",
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert "Napa" in data[0]["medicine_names"]


@pytest.mark.asyncio
async def test_empty_search_returns_empty_list(
    client,
    auth_admin,
    auth_doctor,
):
    """
    Searching with no matching prescriptions returns an empty list.
    """

    response = await client.get(
        "/prescriptions/search",
        params={
            "clinic_id": auth_doctor["doctor"].clinic_id,
            "medication": "MedicineThatDoesNotExist",
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200
    assert response.json() == []