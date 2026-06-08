import pytest

from app.models.prescription import (
    PrescriptionStatus,
)
from app.models.appointment import (
    AppointmentStatus,
)


@pytest.mark.asyncio
async def test_verify_issued_prescription_success(
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
    )

    response = await client.get(
        f"/prescriptions/verify/{prescription.uuid}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["valid"] is True

    assert (
        data["status"]
        == PrescriptionStatus.ISSUED
    )


@pytest.mark.asyncio
async def test_verify_draft_prescription_blocked(
    client,
    auth_doctor,
    auth_patient,
    appointment_factory,
    prescription_factory,
):

    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.DRAFT,
    )

    response = await client.get(
        f"/prescriptions/verify/{prescription.uuid}"
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_verify_invalid_uuid(
    client,
):

    response = await client.get(
        "/prescriptions/verify/"
        "11111111-1111-1111-1111-111111111111"
    )

    assert response.status_code == 404