import pytest

from app.models.clinic import Clinic


@pytest.mark.asyncio
async def test_admin_calendar_requires_clinic_assignment(client, default_clinic,auth_admin):
    response = await client.get(
        f"/appointments/calendar?start_date=2026-01-01&end_date=2026-01-31&clinic_id={default_clinic.id}",
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_admin_calendar_rejects_other_clinic_scope(client, db, default_clinic, auth_admin):
    another_clinic = Clinic(
        name="Another Clinic",
        address="Dhaka",
        phone="01700000001",
        email="another@test.com",
        website="https://another.test",
        primary_color="#111111",
    )

    db.add(another_clinic)
    await db.flush()

    response = await client.get(
        f"/appointments/calendar?start_date=2026-01-01&end_date=2026-01-31&clinic_id={another_clinic.id}",
        headers=auth_admin["headers"],
    )

    assert response.status_code == 403

    body = response.json()

    assert body["error"]["type"] == "ForbiddenError"
    assert body["error"]["message"] == "Admin not authorized for this clinic"


@pytest.mark.asyncio
async def test_admin_calendar_accepts_assigned_clinic_scope(client, default_clinic, auth_admin):
    response = await client.get(
        f"/appointments/calendar?start_date=2026-01-01&end_date=2026-01-31&clinic_id={default_clinic.id}",
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200
    assert response.json() == []
