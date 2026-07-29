import pytest

from app.models.user import User, UserRole
from app.models.clinic import Clinic


@pytest.mark.asyncio
async def test_assign_admin_clinic_success(
    client, db, default_clinic, auth_admin, auth_super_admin
):
    another_clinic = Clinic(
        name="Second Clinic",
        address="Dhaka",
        phone="01700000002",
        email="second@test.com",
        website="https://second.test",
        primary_color="#123456",
    )
    db.add(another_clinic)
    await db.flush()

    # Super admin assigns an existing clinic admin to a clinic (platform action).
    response = await client.post(
        "/admin/clinic/assign-admin",
        json={
            "admin_id": auth_admin["user"].id,
            "clinic_id": another_clinic.id,
        },
        headers=auth_super_admin["headers"],
    )

    assert response.status_code == 200

    body = response.json()
    assert body["id"] == another_clinic.id
    assert body["name"] == another_clinic.name


@pytest.mark.asyncio
async def test_assign_admin_clinic_requires_existing_admin(
    client, db, default_clinic, auth_super_admin
):
    response = await client.post(
        "/admin/clinic/assign-admin",
        json={
            "admin_id": 999999,
            "clinic_id": default_clinic.id,
        },
        headers=auth_super_admin["headers"],
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["type"] == "NotFoundError"
    assert body["error"]["message"] == "Admin not found"


@pytest.mark.asyncio
async def test_assign_admin_clinic_forbidden_for_clinic_admin(
    client, db, default_clinic, auth_admin
):
    # A clinic admin must NOT be able to assign admins to clinics.
    response = await client.post(
        "/admin/clinic/assign-admin",
        json={
            "admin_id": auth_admin["user"].id,
            "clinic_id": default_clinic.id,
        },
        headers=auth_admin["headers"],
    )

    assert response.status_code == 403
