import pytest

from app.models.prescription import PrescriptionStatus
from app.models.appointment import AppointmentStatus


@pytest.mark.asyncio
async def test_download_prescription_pdf_success(
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
        f"/prescriptions/{prescription.id}/pdf",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_draft_prescription_pdf_blocked(
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

    response = await client.get(
        f"/prescriptions/{prescription.id}/pdf",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_patient_cannot_access_other_prescription_pdf(
    client,
    auth_doctor,
    auth_patient,
    auth_another_patient,
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
        f"/prescriptions/{prescription.id}/pdf",
        headers=auth_another_patient["headers"],
    )

    assert response.status_code == 403