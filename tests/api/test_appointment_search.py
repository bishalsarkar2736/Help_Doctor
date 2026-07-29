import pytest
from app.models.appointment import Appointment,AppointmentStatus
from datetime import datetime,timedelta
from app.core.time import UTC
from sqlalchemy import select

@pytest.mark.asyncio
async def test_admin_can_search_appointments(
    client,
    db,
    auth_admin,
    doctor,
    patient_user,
):
    """
    Admin can search appointments.
    """

    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.CONFIRMED,
    )

    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    response = await client.get(
        "/appointments/search",
        params={
            "clinic_id": doctor.clinic_id,
        },
        headers=auth_admin["headers"],
    )

    print(response.status_code)
    print(response.json())

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1

    assert data[0]["id"] == appointment.id
    assert data[0]["patient_id"] == patient_user.id
    assert data[0]["doctor_id"] == doctor.id
    assert data[0]["status"] == AppointmentStatus.CONFIRMED.value



@pytest.mark.asyncio
async def test_patient_cannot_search_appointments(
    client,
    doctor,
    auth_patient,
):
    """
    Patients are not allowed to search appointments.
    """

    response = await client.get(
        "/appointments/search",
        params={
            "clinic_id": doctor.clinic_id,
        },
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_search_by_patient(
    client,
    db,
    auth_admin,
    doctor,
    patient_user,
):
    """
    Search appointments by patient name.
    """

    patient_user.full_name = "John Doe"

    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.CONFIRMED,
    )

    db.add(appointment)
    await db.commit()

    response = await client.get(
        "/appointments/search",
        params={
            "clinic_id": doctor.clinic_id,
            "patient": "John",
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == appointment.id


@pytest.mark.asyncio
async def test_filter_by_status(
    client,
    db,
    auth_admin,
    doctor,
    patient_user,
):
    """
    Filter appointments by status.
    """

    confirmed = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.CONFIRMED,
    )

    waiting = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.WAITING,
    )

    db.add_all([confirmed, waiting])
    await db.commit()

    response = await client.get(
        "/appointments/search",
        params={
            "clinic_id": doctor.clinic_id,
            "status": AppointmentStatus.WAITING.value,
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["status"] == AppointmentStatus.WAITING.value


@pytest.mark.asyncio
async def test_filter_by_date_range(
    client,
    db,
    auth_admin,
    doctor,
    patient_user,
):
    """
    Filter appointments by date range.
    """

    today = datetime.now(UTC)

    inside = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=today,
        status=AppointmentStatus.CONFIRMED,
    )

    outside = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=doctor.clinic_id,
        scheduled_at=today + timedelta(days=10),
        status=AppointmentStatus.CONFIRMED,
    )

    db.add_all([inside, outside])
    await db.commit()

    print("Appointment clinic:", inside.clinic_id)
    print("Doctor clinic:", doctor.clinic_id)
   
    response = await client.get(
        "/appointments/search",
        params={
            "clinic_id": doctor.clinic_id,
            "start_date": today.date().isoformat(),
            "end_date": today.date().isoformat(),
        },
        headers=auth_admin["headers"],
    )

    print(response.json())

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == inside.id



@pytest.mark.asyncio
async def test_empty_search_returns_empty_list(
    client,
    auth_admin,
    doctor,
):
    """
    Searching with no matching appointments returns an empty list.
    """

    response = await client.get(
        "/appointments/search",
        params={
            "clinic_id": doctor.clinic_id,
            "patient": "DoesNotExist",
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_pagination(
    client,
    db,
    auth_admin,
    doctor,
    patient_user,
):
    """
    Search supports limit and offset pagination.
    """

    appointments = [
        Appointment(
            doctor_id=doctor.id,
            patient_id=patient_user.id,
            clinic_id=doctor.clinic_id,
            scheduled_at=datetime.now(UTC) + timedelta(minutes=i*20),
            status=AppointmentStatus.CONFIRMED,
        )
        for i in range(5)
    ]

    db.add_all(appointments)
    await db.commit()

    response = await client.get(
        "/appointments/search",
        params={
            "clinic_id": doctor.clinic_id,
            "limit": 2,
            "offset": 1,
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 2