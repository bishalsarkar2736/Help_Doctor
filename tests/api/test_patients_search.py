from datetime import date
import pytest

from app.models.patient import Patient
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_admin_can_search_patients(
    client,
    db,
    auth_admin,
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