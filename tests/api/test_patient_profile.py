import uuid
import pytest

from app.models.user import User, UserRole
from app.security.jwt import create_access_token


@pytest.fixture
async def profileless_patient(db):
    """A patient account with NO patient profile yet."""
    user = User(
        email=f"np-{uuid.uuid4()}@test.com",
        full_name="No Profile",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    await db.flush()

    token = create_access_token({"sub": str(user.id), "role": "patient"})
    return {"user": user, "headers": {"Authorization": f"Bearer {token}"}}


VALID_BODY = {
    "phone": "01710000000",
    "address": "Dhaka",
    "date_of_birth": "1990-05-15",
    "gender": "MALE",
}


@pytest.mark.asyncio
async def test_get_me_404_when_no_profile(client, profileless_patient):
    res = await client.get("/patients/me", headers=profileless_patient["headers"])
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_create_then_get_profile(client, profileless_patient):
    create = await client.post(
        "/patients/", json=VALID_BODY, headers=profileless_patient["headers"]
    )
    assert create.status_code == 200, create.text
    body = create.json()
    assert body["gender"] == "MALE"
    assert body["date_of_birth"] == "1990-05-15"

    me = await client.get("/patients/me", headers=profileless_patient["headers"])
    assert me.status_code == 200
    assert me.json()["phone"] == "01710000000"


@pytest.mark.asyncio
async def test_create_duplicate_rejected(client, auth_patient):
    # auth_patient already has a profile.
    res = await client.post(
        "/patients/", json=VALID_BODY, headers=auth_patient["headers"]
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_patch_profile(client, auth_patient):
    res = await client.patch(
        "/patients/me",
        json={"phone": "01799999999", "gender": "OTHER"},
        headers=auth_patient["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["phone"] == "01799999999"
    assert body["gender"] == "OTHER"


@pytest.mark.asyncio
async def test_invalid_gender_rejected(client, profileless_patient):
    res = await client.post(
        "/patients/",
        json={**VALID_BODY, "gender": "unknown"},
        headers=profileless_patient["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_profile_forbidden_for_non_patient(client, auth_doctor):
    res = await client.get("/patients/me", headers=auth_doctor["headers"])
    assert res.status_code == 403


# ----------------------------- input validation -----------------------------

@pytest.mark.asyncio
async def test_future_date_of_birth_rejected(client, profileless_patient):
    res = await client.post(
        "/patients/",
        json={**VALID_BODY, "date_of_birth": "2999-01-01"},
        headers=profileless_patient["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_implausibly_old_date_of_birth_rejected(client, profileless_patient):
    res = await client.post(
        "/patients/",
        json={**VALID_BODY, "date_of_birth": "1850-01-01"},
        headers=profileless_patient["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_invalid_phone_rejected(client, profileless_patient):
    res = await client.post(
        "/patients/",
        json={**VALID_BODY, "phone": "abc-123"},
        headers=profileless_patient["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_e164_phone_and_trimming_accepted(client, profileless_patient):
    res = await client.post(
        "/patients/",
        json={**VALID_BODY, "phone": "  +8801710000000  "},
        headers=profileless_patient["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["phone"] == "+8801710000000"  # trimmed


@pytest.mark.asyncio
async def test_patch_rejects_future_dob(client, auth_patient):
    res = await client.patch(
        "/patients/me",
        json={"date_of_birth": "2999-01-01"},
        headers=auth_patient["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_register_trims_and_rejects_blank_name(client):
    # Blank/whitespace-only name is rejected.
    blank = await client.post(
        "/auth/register",
        json={
            "email": f"blank-{uuid.uuid4()}@test.com",
            "full_name": "   ",
            "password": "secret123",
            "role": "patient",
        },
    )
    assert blank.status_code == 422

    # A padded name is trimmed.
    ok = await client.post(
        "/auth/register",
        json={
            "email": f"trim-{uuid.uuid4()}@test.com",
            "full_name": "  Jane Doe  ",
            "password": "secret123",
            "role": "patient",
        },
    )
    assert ok.status_code == 201
    assert ok.json()["full_name"] == "Jane Doe"
