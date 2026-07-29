import pytest
from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User,UserRole



@pytest.mark.asyncio
async def test_admin_can_search_doctors(
    client,
    db,
    auth_admin,
    default_clinic,
):
    """
    Admin can search doctors by name.
    """

    user = User(
        email="doctor-search@test.com",
        full_name="Dr. John Smith",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )

    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=default_clinic.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Cardiologist",
        status=DoctorStatus.APPROVED,
    )

    db.add(doctor)
    await db.commit()

    response = await client.get(
        "/doctors/search",
        params={"q": "John"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == doctor.id
    assert data[0]["full_name"] == "Dr. John Smith"
    assert data[0]["email"] == "doctor-search@test.com"
    assert data[0]["specialization"] == "Cardiology"


@pytest.mark.asyncio
async def test_doctor_can_search_doctors(
    client,
    db,
    auth_doctor,
):
    """
    Doctor can search doctors.
    """

    response = await client.get(
        "/doctors/search",
        params={"q": "Medicine"},
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)



@pytest.mark.asyncio
async def test_receptionist_can_search_doctors(
    client,
    auth_receptionist,
):
    """
    Receptionist can search doctors.
    """

    response = await client.get(
        "/doctors/search",
        params={"q": "Medicine"},
        headers=auth_receptionist["headers"],
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_patient_cannot_search_doctors(
    client,
    auth_patient,
):
    """
    Patients are not allowed to search doctors.
    """

    response = await client.get(
        "/doctors/search",
        params={"q": "Medicine"},
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403



@pytest.mark.asyncio
async def test_search_by_email_and_specialization(
    client,
    db,
    auth_admin,
    default_clinic,
):
    """
    Search should match doctor email and specialization.
    """

    user = User(
        email="neurologist@test.com",
        full_name="Dr. Alice",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )

    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=default_clinic.id,
        specialization="Neurology",
        experience_years=8,
        bio="Neurologist",
        status=DoctorStatus.APPROVED,
    )

    db.add(doctor)
    await db.commit()

    #
    # Search by email
    #
    response = await client.get(
        "/doctors/search",
        params={"q": "neurologist@test.com"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == doctor.id

    #
    # Search by specialization
    #
    response = await client.get(
        "/doctors/search",
        params={"q": "Neurology"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["id"] == doctor.id



@pytest.mark.asyncio
async def test_empty_search_returns_empty_list(
    client,
    auth_admin,
):
    """
    Searching with a non-existent keyword should return an empty list.
    """

    response = await client.get(
        "/doctors/search",
        params={"q": "this-doctor-does-not-exist-12345"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200
    assert response.json() == []



@pytest.mark.asyncio
async def test_search_doctors_pagination(
    client,
    db,
    auth_admin,
    default_clinic,
):
    """
    Doctor search should support limit and offset pagination.
    """

    for i in range(5):
        user = User(
            email=f"doctor{i}@test.com",
            full_name=f"Doctor {i}",
            hashed_password="x",
            role=UserRole.DOCTOR,
            is_active=True,
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

    await db.commit()

    response = await client.get(
        "/doctors/search",
        params={
            "q": "Doctor",
            "limit": 2,
            "offset": 1,
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 2

    # Should return the 2nd and 3rd matching doctors
    assert data[0]["full_name"] == "Doctor 1"
    assert data[1]["full_name"] == "Doctor 2"