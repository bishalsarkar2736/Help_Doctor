"""Patient search, from the endpoint down.

These tests predate clinic scoping and used to create patients with no
appointments at all. That passed while search was role-guarded only — any
staff member could find any patient on the platform. It cannot pass now, and
should not: a patient belongs to a clinic by having been seen there.

So each test books its patients into the searcher's clinic. The assertions
below are unchanged; only the setup gained the relationship the feature is
built on. Cross-tenant behaviour is covered in test_patient_search_scoping.py.
"""

from datetime import date, timedelta
from itertools import count

import pytest
from sqlalchemy.dialects.postgresql import Range

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Patient
from app.models.user import User, UserRole


@pytest.fixture
async def clinic_doctor(db, default_clinic):
    """Somebody for the patients below to have an appointment with."""
    user = User(
        email="search-fixture-doctor@test.com",
        full_name="Dr Fixture",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=default_clinic.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()

    return doctor


_slot = count(1)


async def _seen_at(db, clinic, doctor, patient_user):
    """Make `patient_user` one of `clinic`'s patients.

    Each appointment gets its own hour: time_range is exclusion-constrained
    per doctor, so booking two patients into the same slot fails on the
    database rather than in the assertion.
    """
    start = utc_now() + timedelta(hours=next(_slot))

    db.add(
        Appointment(
            patient_id=patient_user.id,
            doctor_id=doctor.id,
            clinic_id=clinic.id,
            scheduled_at=start,
            status=AppointmentStatus.PENDING,
            time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_admin_can_search_patients(
    client,
    db,
    auth_admin,
    default_clinic,
    clinic_doctor,
):
    """
    Admin can search patients.
    """

    user = User(
        email="john@test.com",
        full_name="John Smith",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    patient = Patient(
        user_id=user.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )
    db.add(patient)

    await _seen_at(db, default_clinic, clinic_doctor, user)
    await db.commit()

    response = await client.get(
        "/patients/search",
        params={"q": "john"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == patient.id
    assert data[0]["full_name"] == "John Smith"
    assert data[0]["email"] == "john@test.com"
    assert data[0]["phone"] == "01711111111"


@pytest.mark.asyncio
async def test_doctor_can_search_patients(
    client,
    db,
    auth_doctor,
    default_clinic,
    clinic_doctor,
):
    """
    Doctor can search patients.
    """

    user = User(
        email="john-doctor@test.com",
        full_name="John Smith",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    patient = Patient(
        user_id=user.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )
    db.add(patient)

    await _seen_at(db, default_clinic, clinic_doctor, user)
    await db.commit()

    response = await client.get(
        "/patients/search",
        params={"q": "john"},
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == patient.id
    assert data[0]["full_name"] == "John Smith"
    assert data[0]["email"] == "john-doctor@test.com"
    assert data[0]["phone"] == "01711111111"


@pytest.mark.asyncio
async def test_receptionist_can_search_patients(
    client,
    db,
    auth_receptionist,
    default_clinic,
    clinic_doctor,
):
    """
    Receptionist can search patients.
    """

    user = User(
        email="john-reception@test.com",
        full_name="John Smith",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )

    db.add(user)
    await db.flush()

    patient = Patient(
        user_id=user.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )

    db.add(patient)

    await _seen_at(db, default_clinic, clinic_doctor, user)
    await db.commit()

    response = await client.get(
        "/patients/search",
        params={"q": "john"},
        headers=auth_receptionist["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == patient.id
    assert data[0]["full_name"] == "John Smith"
    assert data[0]["email"] == "john-reception@test.com"
    assert data[0]["phone"] == "01711111111"



@pytest.mark.asyncio
async def test_patient_cannot_search_patients(
    client,
    auth_patient,
):
    """
    Patients are not allowed to search all patients.
    """

    response = await client.get(
        "/patients/search",
        params={"q": "john"},
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_search_by_full_name(
    client,
    db,
    auth_admin,
    default_clinic,
    clinic_doctor,
):
    """
    Search should return patients matching the full name.
    """

    user1 = User(
        email="alice@test.com",
        full_name="Alice Johnson",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user1)
    await db.flush()

    patient1 = Patient(
        user_id=user1.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="FEMALE",
    )

    user2 = User(
        email="bob@test.com",
        full_name="Bob Smith",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user2)
    await db.flush()

    patient2 = Patient(
        user_id=user2.id,
        phone="01822222222",
        address="Dhaka",
        date_of_birth=date(1994, 1, 1),
        gender="MALE",
    )

    db.add_all([patient1, patient2])

    await _seen_at(db, default_clinic, clinic_doctor, user1)
    await _seen_at(db, default_clinic, clinic_doctor, user2)
    await db.commit()

    response = await client.get(
        "/patients/search",
        params={"q": "alice"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == patient1.id
    assert data[0]["full_name"] == "Alice Johnson"
    assert data[0]["email"] == "alice@test.com"


@pytest.mark.asyncio
async def test_search_by_email(
    client,
    db,
    auth_admin,
    default_clinic,
    clinic_doctor,
):
    """
    Search should return patients matching the email.
    """

    user1 = User(
        email="alice@example.com",
        full_name="Alice Johnson",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user1)
    await db.flush()

    patient1 = Patient(
        user_id=user1.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="FEMALE",
    )

    user2 = User(
        email="bob@example.com",
        full_name="Bob Smith",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user2)
    await db.flush()

    patient2 = Patient(
        user_id=user2.id,
        phone="01822222222",
        address="Dhaka",
        date_of_birth=date(1994, 1, 1),
        gender="MALE",
    )

    db.add_all([patient1, patient2])

    await _seen_at(db, default_clinic, clinic_doctor, user1)
    await _seen_at(db, default_clinic, clinic_doctor, user2)
    await db.commit()

    response = await client.get(
        "/patients/search",
        params={"q": "alice@example.com"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == patient1.id
    assert data[0]["full_name"] == "Alice Johnson"
    assert data[0]["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_search_by_phone(
    client,
    db,
    auth_admin,
    default_clinic,
    clinic_doctor,
):
    """
    Search should return patients matching the phone number.
    """

    user1 = User(
        email="alice-phone@test.com",
        full_name="Alice Johnson",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user1)
    await db.flush()

    patient1 = Patient(
        user_id=user1.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="FEMALE",
    )

    user2 = User(
        email="bob-phone@test.com",
        full_name="Bob Smith",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user2)
    await db.flush()

    patient2 = Patient(
        user_id=user2.id,
        phone="01822222222",
        address="Dhaka",
        date_of_birth=date(1994, 1, 1),
        gender="MALE",
    )

    db.add_all([patient1, patient2])

    await _seen_at(db, default_clinic, clinic_doctor, user1)
    await _seen_at(db, default_clinic, clinic_doctor, user2)
    await db.commit()

    response = await client.get(
        "/patients/search",
        params={"q": "01711111111"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == patient1.id
    assert data[0]["full_name"] == "Alice Johnson"
    assert data[0]["phone"] == "01711111111"


@pytest.mark.asyncio
async def test_empty_search_returns_empty_list(
    client,
    db,
    auth_admin,
    default_clinic,
    clinic_doctor,
):
    """
    Search should return an empty list when no patients match.
    """

    user = User(
        email="john@test.com",
        full_name="John Smith",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )

    db.add(user)
    await db.flush()

    patient = Patient(
        user_id=user.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )

    db.add(patient)

    await _seen_at(db, default_clinic, clinic_doctor, user)
    await db.commit()

    response = await client.get(
        "/patients/search",
        params={"q": "zzzzzzzz"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200
    assert response.json() == []



@pytest.mark.asyncio
async def test_search_pagination(
    client,
    db,
    auth_admin,
    default_clinic,
    clinic_doctor,
):
    """
    Search endpoint should support limit and offset.
    """

    for i in range(5):
        user = User(
            email=f"patient{i}@test.com",
            full_name=f"Patient {i}",
            hashed_password="x",
            role=UserRole.PATIENT,
            is_active=True,
        )
        db.add(user)
        await db.flush()

        patient = Patient(
            user_id=user.id,
            phone=f"0170000000{i}",
            address="Dhaka",
            date_of_birth=date(1995, 1, 1),
            gender="MALE",
        )

        db.add(patient)

        await _seen_at(db, default_clinic, clinic_doctor, user)

    await db.commit()

    response = await client.get(
        "/patients/search",
        params={
            "q": "Patient",
            "limit": 2,
            "offset": 1,
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 2