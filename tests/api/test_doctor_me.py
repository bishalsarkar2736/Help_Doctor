import uuid
import pytest

from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.security.jwt import create_access_token


async def _make_doctor_user(db, clinic_id=None, status=DoctorStatus.PENDING, with_profile=True):
    user = User(
        email=f"doc-{uuid.uuid4()}@test.com",
        full_name="Dr Own",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
        clinic_id=clinic_id,
    )
    db.add(user)
    await db.flush()

    doctor = None
    if with_profile:
        doctor = Doctor(
            user_id=user.id,
            specialization="Cardiology",
            experience_years=4,
            bio="Test",
            clinic_id=clinic_id,
            status=status,
        )
        db.add(doctor)
        await db.flush()
        await db.refresh(doctor)

    token = create_access_token(
        data={"sub": str(user.id), "role": UserRole.DOCTOR.value}
    )
    headers = {"Authorization": f"Bearer {token}"}
    return user, doctor, headers


@pytest.mark.asyncio
async def test_doctors_me_returns_own_approved_profile(client, auth_doctor):
    res = await client.get("/doctors/me", headers=auth_doctor["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "APPROVED"
    assert body["specialization"] == "Medicine"
    assert body["clinic_id"] is not None
    assert body["clinic_name"] is not None


@pytest.mark.asyncio
async def test_doctors_me_visible_while_pending(client, db, default_clinic):
    _, doctor, headers = await _make_doctor_user(
        db, clinic_id=default_clinic.id, status=DoctorStatus.PENDING
    )
    res = await client.get("/doctors/me", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == doctor.id
    assert body["status"] == "PENDING"


@pytest.mark.asyncio
async def test_doctors_me_404_when_no_profile(client, db):
    _, _, headers = await _make_doctor_user(db, with_profile=False)
    res = await client.get("/doctors/me", headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_doctors_me_forbidden_for_patient(client, auth_patient):
    res = await client.get("/doctors/me", headers=auth_patient["headers"])
    assert res.status_code == 403
