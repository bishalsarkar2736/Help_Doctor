from datetime import datetime, timedelta

from app.models.appointment import Appointment, AppointmentStatus
from app.core.time import UTC


async def test_doctor_can_complete_consultation_via_endpoint(
    db,
    client,
    auth_doctor,
    patient_user,
):
    appointment = Appointment(
        doctor_id=auth_doctor["doctor"].id,
        patient_id=patient_user.id,
        clinic_id=auth_doctor["doctor"].clinic_id,
        scheduled_at=datetime.now(UTC) - timedelta(minutes=40),
        status=AppointmentStatus.IN_CONSULTATION,
    )
    db.add(appointment)
    await db.flush()
    await db.refresh(appointment)

    response = await client.post(
        f"/appointments/{appointment.id}/complete-consultation",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["completed_at"] is not None
