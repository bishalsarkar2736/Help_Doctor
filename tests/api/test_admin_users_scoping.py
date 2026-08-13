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


# ---------------------------------------------------------------------------
# The realtime fan-out, which the endpoint check above does not cover
#
# toggle-active is correctly scoped: an admin can only toggle a user inside
# their own clinic. But having done so it calls notify_admins(), which selects
# `User.role == ADMIN` with no clinic predicate and pushes the event to every
# admin on the platform. The authorization is right and the broadcast is wrong,
# so no test of the endpoint's status code can see it.
#
# What leaks today is thin — a user id and a boolean — but it is another
# tenant's admin panel receiving events about a clinic it has no relationship
# with, and the next caller of notify_admins decides how thin it stays.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggling_a_user_notifies_only_the_admins_of_that_clinic(
    client, db, default_clinic, auth_admin, other_clinic_admin, monkeypatch
):
    staff = await _user(db, UserRole.RECEPTIONIST, default_clinic.id)
    await db.flush()

    notified: list[int] = []

    async def _capture(*, user_id, payload):
        notified.append(user_id)

    # Patched on realtime_service, where notify_admins resolves the name, so
    # this captures the fan-out only -- the route's separate direct call to
    # send_realtime_sync for the affected user goes through its own import and
    # is deliberately not counted here.
    monkeypatch.setattr(
        "app.services.realtime_service.send_realtime_sync", _capture
    )

    res = await client.post(
        f"/admin/users/{staff.id}/toggle-active",
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text

    # The paired allow-case: the clinic's own admin panel must still update.
    assert auth_admin["user"].id in notified, (
        "the acting clinic's own admin was not notified -- the fan-out is "
        "scoped too tightly, not just enough"
    )

    assert other_clinic_admin["user"].id not in notified, (
        "another clinic's admin received a realtime event about a user they "
        "have no relationship with"
    )
