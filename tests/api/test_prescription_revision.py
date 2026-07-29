import pytest
from sqlalchemy import select

from app.models.prescription import (
    Prescription,
    PrescriptionStatus,
)

from app.models.appointment import (
    AppointmentStatus,
)


@pytest.mark.asyncio
async def test_create_prescription_revision_success(
    db,
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
        == PrescriptionStatus.DRAFT.value
    )

    refreshed = await db.scalar(
        select(Prescription).where(
            Prescription.id == prescription.id
        )
    )

    assert refreshed is not None
    assert refreshed.status == PrescriptionStatus.LOCKED
    assert refreshed.is_latest_revision is False


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
async def test_issue_draft_revision_endpoint(
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

    create_revision_response = await client.post(
        f"/prescriptions/{prescription.id}/revisions",
        json={
            "notes": "Updated draft revision",
            "items": [
                {
                    "medicine_name": "Ace",
                    "dosage": "500mg",
                    "frequency": "2x daily",
                    "duration_days": 5,
                    "instructions": "After meal",
                }
            ],
        },
        headers=auth_doctor["headers"],
    )

    assert create_revision_response.status_code == 201
    revision_data = create_revision_response.json()

    issue_response = await client.post(
        f"/prescriptions/{prescription.id}/revisions/issue",
        headers=auth_doctor["headers"],
    )

    assert issue_response.status_code == 200
    assert issue_response.json()["message"] == "prescription_revision_issued"
    assert revision_data["status"] == PrescriptionStatus.DRAFT.value


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