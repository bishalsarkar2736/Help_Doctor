import pytest


# ---- Fix 1: super_admin can bootstrap via /users/me ----

@pytest.mark.asyncio
async def test_super_admin_can_read_me(client, auth_super_admin):
    res = await client.get("/users/me", headers=auth_super_admin["headers"])
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "super_admin"
    assert body["clinic_id"] is None


@pytest.mark.asyncio
async def test_admin_me_includes_clinic_id(client, default_clinic, auth_admin):
    res = await client.get("/users/me", headers=auth_admin["headers"])
    assert res.status_code == 200
    assert res.json()["clinic_id"] == default_clinic.id


# ---- Fix 2: /medicines/assistant resolves clinic_id (no more 500) ----

@pytest.mark.asyncio
async def test_medicine_assistant_works_for_doctor(
    client, default_clinic, auth_doctor
):
    res = await client.post(
        "/medicines/assistant",
        json={"question": "what is paracetamol"},
        headers=auth_doctor["headers"],
    )
    assert res.status_code == 200, res.text
    assert isinstance(res.json()["answer"], str)


@pytest.mark.asyncio
async def test_medicine_assistant_requires_auth(client):
    res = await client.post(
        "/medicines/assistant",
        json={"question": "what is paracetamol"},
    )
    assert res.status_code == 401
