import pytest

from app.models.prescription import (
    PrescriptionStatus,
)

from app.models.appointment import (
    AppointmentStatus,
)


@pytest.mark.asyncio
async def test_create_prescription_revision_success(
    client,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):
    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.ISSUED,
        revision_number=1,
        is_latest_revision=True,
    )

    payload = {
        "notes": "Updated medicine",
        "items": [
            {
                "medicine_name": "Ace",
                "dosage": "500mg",
                "frequency": "2x daily",
                "duration_days": 5,
                "instructions": "After meal",
            }
        ],
    }

    response = await client.post(
        f"/prescriptions/{prescription.id}/revisions",
        json=payload,
        headers=auth_doctor["headers"],
    )

    print("\nSTATUS:", response.status_code)
    print("BODY:", response.text)

    assert response.status_code == 201

    data = response.json()

    assert (
        data["revision_number"]
        == 2
    )

    assert (
        data["is_latest_revision"]
        is True
    )

    assert (
        data["status"]
        == PrescriptionStatus.ISSUED.value
    )


@pytest.mark.asyncio
async def test_non_issued_prescription_cannot_be_revised(
    client,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):
    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.DRAFT,
    )

    payload = {
        "notes": "Updated",
        "items": [
            {
                "medicine_name": "Ace",
            }
        ],
    }

    response = await client.post(
        f"/prescriptions/{prescription.id}/revisions",
        json=payload,
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_non_latest_revision_cannot_be_revised(
    client,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):
    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.SUPERSEDED,
        revision_number=1,
        is_latest_revision=False,
    )

    payload = {
        "notes": "Updated",
        "items": [
            {
                "medicine_name": "Ace",
            }
        ],
    }

    response = await client.post(
        f"/prescriptions/{prescription.id}/revisions",
        json=payload,
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_doctor_cannot_revise_other_doctor_prescription(
    client,
    auth_another_doctor,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):
    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.ISSUED,
        revision_number=1,
        is_latest_revision=True,
    )

    payload = {
        "notes": "Updated",
        "items": [
            {
                "medicine_name": "Ace",
            }
        ],
    }

    response = await client.post(
        f"/prescriptions/{prescription.id}/revisions",
        json=payload,
        headers=auth_another_doctor["headers"]
    )

    assert response.status_code == 403