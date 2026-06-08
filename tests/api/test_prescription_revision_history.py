import pytest


@pytest.mark.asyncio
async def test_prescription_revision_history_success(
    client,
    auth_doctor,
    prescription_factory,
    appointment_factory,
):
    appointment = await appointment_factory(
        patient_id=auth_doctor["doctor"].user_id,
        doctor_id=auth_doctor["doctor"].id,
        status="COMPLETED",
    )

    base = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_doctor["doctor"].user_id,
        status="ISSUED",
        revision_number=1,
        is_latest_revision=False,
    )

    response = await client.get(
        f"/prescriptions/{base.id}/revisions/history",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200
    data = response.json()

    assert "items" in data