import uuid

import pytest

from app.models.user import User, UserRole
from app.models.clinic import Clinic


async def _user(db, role, clinic_id):
    u = User(
        email=f"{role.value}-{uuid.uuid4()}@test.com",
        full_name="Test User",
        hashed_password="x",
        role=role,
        is_active=True,
        clinic_id=clinic_id,
    )
    db.add(u)
    await db.flush()
    return u


@pytest.mark.asyncio
async def test_admin_users_scoped_to_own_clinic(client, db, default_clinic, auth_admin):
    # A second clinic with its own staff.
    other = Clinic(name="Other Clinic", address="X", phone="02", email="o@test.com")
    db.add(other)
    await db.flush()

    same = await _user(db, UserRole.RECEPTIONIST, default_clinic.id)
    outsider = await _user(db, UserRole.DOCTOR, other.id)
    patient = await _user(db, UserRole.PATIENT, None)
    await db.flush()

    res = await client.get("/admin/users", headers=auth_admin["headers"])
    assert res.status_code == 200, res.text
    ids = {u["id"] for u in res.json()}

    assert same.id in ids
    assert auth_admin["user"].id in ids  # the admin themselves
    assert outsider.id not in ids  # another clinic's staff hidden
    assert patient.id not in ids  # patients (no clinic) hidden

    # Every row is scoped to the admin's clinic and exposes clinic_id.
    assert all(u["clinic_id"] == default_clinic.id for u in res.json())


@pytest.mark.asyncio
async def test_admin_cannot_toggle_other_clinic_user(client, db, default_clinic, auth_admin):
    other = Clinic(name="Other Clinic 2", address="X", phone="03", email="o2@test.com")
    db.add(other)
    await db.flush()
    outsider = await _user(db, UserRole.DOCTOR, other.id)
    await db.flush()

    res = await client.post(
        f"/admin/users/{outsider.id}/toggle-active",
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403, res.text
