import uuid
import pytest

from app.models.user import User, UserRole
from app.models.clinic import ClinicStatus
from app.security.jwt import hash_password
from app.services.auth_service import authentication_user
from app.services.clinic_service import (
    suspend_clinic,
    activate_clinic,
    soft_delete_clinic,
)
from app.try_except.exceptions import ForbiddenError


async def _clinic_admin_with_password(db, clinic_id, password="secret123"):
    user = User(
        email=f"cadmin-{uuid.uuid4()}@test.com",
        full_name="Clinic Admin",
        hashed_password=hash_password(password),
        role=UserRole.ADMIN,
        is_active=True,
        is_email_verified=True,
        clinic_id=clinic_id,
    )
    db.add(user)
    await db.flush()
    return user


# ----------------------- ENDPOINTS (super admin) -----------------------

@pytest.mark.asyncio
async def test_super_admin_suspend_activate_delete(
    client, default_clinic, auth_super_admin
):
    cid = default_clinic.id
    h = auth_super_admin["headers"]

    suspend = await client.post(f"/admin/clinic/{cid}/suspend", headers=h)
    assert suspend.status_code == 200, suspend.text
    assert suspend.json()["status"] == "SUSPENDED"
    assert suspend.json()["suspended_at"] is not None

    activate = await client.post(f"/admin/clinic/{cid}/activate", headers=h)
    assert activate.status_code == 200
    assert activate.json()["status"] == "ACTIVE"
    assert activate.json()["suspended_at"] is None

    deleted = await client.delete(f"/admin/clinic/{cid}", headers=h)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "DELETED"
    assert deleted.json()["deleted_at"] is not None


@pytest.mark.asyncio
async def test_clinic_admin_cannot_suspend_clinic(
    client, default_clinic, auth_admin
):
    res = await client.post(
        f"/admin/clinic/{default_clinic.id}/suspend",
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_cannot_suspend_deleted_clinic(
    client, default_clinic, auth_super_admin
):
    cid = default_clinic.id
    h = auth_super_admin["headers"]

    await client.delete(f"/admin/clinic/{cid}", headers=h)
    res = await client.post(f"/admin/clinic/{cid}/suspend", headers=h)
    assert res.status_code == 400


# ----------------------- LOGIN CASCADE (service level) -----------------------

@pytest.mark.asyncio
async def test_login_blocked_when_clinic_suspended(db, default_clinic):
    admin = await _clinic_admin_with_password(db, default_clinic.id)

    # Active clinic → login works.
    token = await authentication_user(db, admin.email, "secret123")
    assert token["access_token"]

    # Suspend → login blocked.
    await suspend_clinic(db, default_clinic.id)
    with pytest.raises(ForbiddenError):
        await authentication_user(db, admin.email, "secret123")

    # Reactivate → login works again.
    await activate_clinic(db, default_clinic.id)
    token2 = await authentication_user(db, admin.email, "secret123")
    assert token2["access_token"]


@pytest.mark.asyncio
async def test_login_blocked_when_clinic_deleted(db, default_clinic):
    admin = await _clinic_admin_with_password(db, default_clinic.id)

    await soft_delete_clinic(db, default_clinic.id)
    with pytest.raises(ForbiddenError):
        await authentication_user(db, admin.email, "secret123")


@pytest.mark.asyncio
async def test_patient_login_unaffected_by_clinic_status(db, default_clinic):
    # Patients are not clinic-bound.
    patient = User(
        email=f"pat-{uuid.uuid4()}@test.com",
        full_name="Pat",
        hashed_password=hash_password("secret123"),
        role=UserRole.PATIENT,
        is_active=True,
        is_email_verified=True,
    )
    db.add(patient)
    await db.flush()

    await suspend_clinic(db, default_clinic.id)

    token = await authentication_user(db, patient.email, "secret123")
    assert token["access_token"]
