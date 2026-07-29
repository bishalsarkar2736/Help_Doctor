from datetime import date
import pytest
from datetime import datetime, timedelta

from app.core.time import UTC
from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)
from app.models.user import User, UserRole
from app.models.patient import Patient
import uuid

@pytest.mark.asyncio
async def test_patient_can_view_own_queue_position(
    client,
    db,
    doctor,
    auth_patient,
):
    """
    A patient can retrieve the queue position of their own appointment.
    """

    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=auth_patient["user"].id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.WAITING,
        waiting_started_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    response = await client.get(
        f"/appointments/{appointment.id}/queue-position",
        headers=auth_patient["headers"],
    )


    assert response.status_code == 200

    data = response.json()

    assert data["appointment_id"] == appointment.id
    assert data["patient_name"] == (
        auth_patient["user"].full_name or ""
    )
    assert data["position"] == 1
    assert data["estimated_wait_minutes"] == 0


@pytest.mark.asyncio
async def test_patient_cannot_view_other_patient_queue(
    client,
    db,
    doctor,
    auth_patient,
):
    """
    A patient must not be able to access another patient's queue position.
    """

    other_user = User(
        email=f"other-{uuid.uuid4()}@test.com",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(other_user)
    await db.flush()

    db.add(
        Patient(
            user_id=other_user.id,
            phone="01700000000",
            address="Dhaka",
            gender="MALE",
            date_of_birth=date(1995, 1, 1),
        )
    )
    await db.flush()

    #
    # Appointment belongs to OTHER patient
    #
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=other_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.WAITING,
        waiting_started_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    #
    # Logged-in patient tries to access it
    #
    response = await client.get(
        f"/appointments/{appointment.id}/queue-position",
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403



@pytest.mark.asyncio
async def test_doctor_can_view_queue_position(
    client,
    db,
    auth_doctor,
    patient_user,
):
    """
    The assigned doctor can view a patient's queue position.
    """

    appointment = Appointment(
        doctor_id=auth_doctor["doctor"].id,
        patient_id=patient_user.id,
        clinic_id=auth_doctor["doctor"].clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.WAITING,
        waiting_started_at=datetime.now(UTC) - timedelta(minutes=10),
    )

    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    response = await client.get(
        f"/appointments/{appointment.id}/queue-position",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["appointment_id"] == appointment.id
    assert data["position"] == 1
    assert data["estimated_wait_minutes"] == 0



@pytest.mark.asyncio
async def test_other_doctor_cannot_view_queue_position(
    client,
    db,
    doctor,
    another_doctor,
    patient_user,
    auth_another_doctor,
):
    """
    Another doctor cannot view someone else's queue.
    """

    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.WAITING,
        waiting_started_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    response = await client.get(
        f"/appointments/{appointment.id}/queue-position",
        headers=auth_another_doctor["headers"],
    )

    assert response.status_code == 403



@pytest.mark.asyncio
async def test_queue_position_is_correct(
    client,
    db,
    doctor,
    patient_user,
    another_patient_user,
    auth_patient,
):
    """
    Queue position should reflect waiting order.
    """

    first = Appointment(
        doctor_id=doctor.id,
        patient_id=another_patient_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.WAITING,
        waiting_started_at=datetime.now(UTC) - timedelta(minutes=20),
    )

    second = Appointment(
        doctor_id=doctor.id,
        patient_id=auth_patient["user"].id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.WAITING,
        waiting_started_at=datetime.now(UTC) - timedelta(minutes=10),
    )

    db.add_all([first, second])
    await db.commit()
    await db.refresh(second)

    response = await client.get(
        f"/appointments/{second.id}/queue-position",
        headers=auth_patient["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["position"] == 2
    assert data["estimated_wait_minutes"] == 20



@pytest.mark.asyncio
async def test_non_waiting_patient_returns_none_position(
    client,
    db,
    doctor,
    auth_patient,
):
    """
    Patients not in WAITING state have no queue position.
    """

    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=auth_patient["user"].id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.CONFIRMED,
    )

    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    response = await client.get(
        f"/appointments/{appointment.id}/queue-position",
        headers=auth_patient["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["position"] is None
    assert data["estimated_wait_minutes"] == 0



