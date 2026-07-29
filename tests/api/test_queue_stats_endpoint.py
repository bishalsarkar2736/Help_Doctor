import pytest
from datetime import datetime, timedelta

from app.core.time import UTC
from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)
from app.models.user import User, UserRole




@pytest.mark.asyncio
async def test_doctor_can_view_queue_stats(
    client,
    db,
    auth_doctor,
    patient_user,
):
    """
    Doctor can retrieve live queue statistics.
    """

    current = Appointment(
        doctor_id=auth_doctor["doctor"].id,
        patient_id=patient_user.id,
        clinic_id=auth_doctor["doctor"].clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.IN_CONSULTATION,
    )

    waiting = Appointment(
        doctor_id=auth_doctor["doctor"].id,
        patient_id=patient_user.id,
        clinic_id=auth_doctor["doctor"].clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.WAITING,
        waiting_started_at=datetime.now(UTC) - timedelta(minutes=15),
    )

    db.add_all([current, waiting])

    await db.commit()

    response = await client.get(
        "/appointments/doctor/queue/stats",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["waiting_count"] == 1
    assert data["average_wait_minutes"] >= 0

    assert data["current_patient"] is not None
    assert data["current_patient"]["appointment_id"] == current.id

    assert data["next_patient"] is not None
    assert data["next_patient"]["appointment_id"] == waiting.id



@pytest.mark.asyncio
async def test_empty_queue_stats(
    client,
    auth_doctor,
):
    """
    Queue statistics should be empty when there are no patients.
    """

    response = await client.get(
        "/appointments/doctor/queue/stats",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["current_patient"] is None
    assert data["next_patient"] is None
    assert data["waiting_count"] == 0
    assert data["average_wait_minutes"] == 0



@pytest.mark.asyncio
async def test_queue_stats_average_wait(
    client,
    db,
    auth_doctor,
    auth_patient,
):
    """
    Average waiting time should be calculated correctly.
    """

    now = datetime.now(UTC)

    appointment1 = Appointment(
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        clinic_id=auth_doctor["doctor"].clinic_id,
        scheduled_at=now,
        status=AppointmentStatus.WAITING,
        waiting_started_at=now - timedelta(minutes=10),
    )

    appointment2 = Appointment(
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        clinic_id=auth_doctor["doctor"].clinic_id,
        scheduled_at=now,
        status=AppointmentStatus.WAITING,
        waiting_started_at=now - timedelta(minutes=30),
    )

    db.add_all([appointment1, appointment2])

    await db.commit()

    response = await client.get(
        "/appointments/doctor/queue/stats",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["waiting_count"] == 2

    # (10 + 30) / 2
    assert data["average_wait_minutes"] == 20