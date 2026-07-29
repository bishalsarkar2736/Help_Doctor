import pytest

from app.models.clinic import Clinic, ClinicStatus


@pytest.mark.asyncio
async def test_super_admin_lists_clinics(client, db, default_clinic, auth_super_admin):
    # A second, suspended clinic.
    other = Clinic(name="Second Clinic", status=ClinicStatus.SUSPENDED)
    db.add(other)
    await db.flush()

    res = await client.get("/admin/clinics", headers=auth_super_admin["headers"])
    assert res.status_code == 200
    names = {c["name"] for c in res.json()}
    assert "Test Clinic" in names
    assert "Second Clinic" in names


@pytest.mark.asyncio
async def test_clinics_list_status_filter(client, db, default_clinic, auth_super_admin):
    other = Clinic(name="Suspended One", status=ClinicStatus.SUSPENDED)
    db.add(other)
    await db.flush()

    res = await client.get(
        "/admin/clinics",
        params={"status": "SUSPENDED"},
        headers=auth_super_admin["headers"],
    )
    assert res.status_code == 200
    body = res.json()
    assert all(c["status"] == "SUSPENDED" for c in body)
    assert any(c["name"] == "Suspended One" for c in body)


@pytest.mark.asyncio
async def test_clinics_list_forbidden_for_clinic_admin(client, default_clinic, auth_admin):
    res = await client.get("/admin/clinics", headers=auth_admin["headers"])
    assert res.status_code == 403
