"""Two endpoints that answered questions about resources the caller does not own.

FINDING 5 — GET /users/{user_id}/presence
The route checked that the caller was *a* valid user and then passed the
client-supplied id straight to is_user_online(). Any authenticated principal of
any role could poll any user id, across clinics and across roles, and user ids
are sequential.

THE POLICY PINNED HERE, AND WHY IT IS THIS NARROW
Nothing in the frontend calls this endpoint — no reference to /presence,
isOnline or is_online anywhere in src/ — and is_user_online has no other caller
in the backend. So there is no existing UI workflow that needs a DOCTOR to see
a colleague's presence, or a PATIENT to see their treating doctor's. Granting
either would be inventing a feature, so both are denied and pinned as denied.
What remains is the front-desk case the audit approved: clinic staff seeing
their own clinic's people.

    own presence            every role
    ADMIN / RECEPTIONIST    users of their own clinic
    DOCTOR                  themselves only
    PATIENT                 themselves only
    anyone else's clinic    denied

A DOCTOR's clinic is read from their Doctor row, not User.clinic_id — the
asymmetry _searcher_clinic_id and _caller_clinic_id already document. The test
fixtures leave User.clinic_id NULL for doctors, so a naive User-only rule would
deny a receptionist their own clinic's doctor.

NOT AN EXISTENCE ORACLE. An unknown id and a real id belonging to another
clinic must be indistinguishable, so probing cannot enumerate the user table.

FINDING 6 — notification analytics
/admin/analytics/notifications and /notifications/daily aggregate every
Notification row on the platform, while the seven sibling routes in the same
module all resolve a clinic. Notification has no clinic_id and patient users
have clinic_id NULL, so a clinic join would silently drop patient
notifications from every total — inventing a number rather than scoping one.
The endpoints are therefore platform telemetry, and belong to the platform
role.
"""

import pytest
import pytest_asyncio
import uuid

from app.models.user import User, UserRole
from app.security.jwt import create_access_token

#: Far outside anything the fixtures create.
UNKNOWN_USER_ID = 9_900_001


@pytest_asyncio.fixture
async def second_clinic_receptionist(db, second_clinic):
    """A real user of another clinic — the control for the unknown-id case."""
    user = User(
        email=f"recep-b-{uuid.uuid4()}@test.com",
        full_name="Clinic B Reception",
        hashed_password="x",
        role=UserRole.RECEPTIONIST,
        is_active=True,
        clinic_id=second_clinic.id,
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Finding 5 — presence
# ---------------------------------------------------------------------------


async def _assert_own_presence_allowed(client, principal):
    res = await client.get(
        f"/users/{principal['user'].id}/presence",
        headers=principal["headers"],
    )

    assert res.status_code == 200, res.text
    assert res.json()["user_id"] == principal["user"].id
    assert "online" in res.json()


# Written out per role rather than parametrised: these fixtures are async, and
# request.getfixturevalue cannot resolve an async fixture from inside a running
# event loop.


@pytest.mark.asyncio
async def test_an_admin_may_see_their_own_presence(client, auth_admin):
    """1. Own presence is always allowed — the one case with no ambiguity."""
    await _assert_own_presence_allowed(client, auth_admin)


@pytest.mark.asyncio
async def test_a_receptionist_may_see_their_own_presence(client, auth_receptionist):
    await _assert_own_presence_allowed(client, auth_receptionist)


@pytest.mark.asyncio
async def test_a_doctor_may_see_their_own_presence(client, auth_doctor):
    await _assert_own_presence_allowed(client, auth_doctor)


@pytest.mark.asyncio
async def test_a_patient_may_see_their_own_presence(client, auth_patient):
    await _assert_own_presence_allowed(client, auth_patient)


@pytest.mark.asyncio
async def test_admin_may_see_a_receptionist_of_their_own_clinic(
    client, db, default_clinic, auth_admin, auth_receptionist
):
    """2. The front-desk case the audit approved."""

    res = await client.get(
        f"/users/{auth_receptionist['user'].id}/presence",
        headers=auth_admin["headers"],
    )

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_receptionist_may_see_a_doctor_of_their_own_clinic(
    client, db, default_clinic, auth_receptionist, auth_doctor
):
    """2b. A doctor's clinic lives on the Doctor row. A rule that read only
    User.clinic_id would deny this, since doctors carry NULL there."""

    res = await client.get(
        f"/users/{auth_doctor['user'].id}/presence",
        headers=auth_receptionist["headers"],
    )

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_admin_cannot_see_another_clinics_user(
    client, db, auth_admin, second_clinic_receptionist
):
    """3. THE CORE PROPERTY."""

    res = await client.get(
        f"/users/{second_clinic_receptionist.id}/presence",
        headers=auth_admin["headers"],
    )

    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_admin_cannot_see_another_clinics_doctor(
    client, db, auth_admin, other_clinic_doctor
):
    """3b. Same rule through the Doctor row."""

    res = await client.get(
        f"/users/{other_clinic_doctor['user'].id}/presence",
        headers=auth_admin["headers"],
    )

    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_patient_cannot_inspect_an_unrelated_user(
    client, db, auth_patient, auth_receptionist
):
    """4. A patient is not staff and has no clinic to be inside."""

    res = await client.get(
        f"/users/{auth_receptionist['user'].id}/presence",
        headers=auth_patient["headers"],
    )

    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_patient_cannot_inspect_their_treating_doctor(
    client, db, auth_patient, auth_doctor, appointment_factory
):
    """5. PINNED AS DENIED, deliberately.

    The audit allowed this only "if an existing UI actually requires it".
    Nothing in the frontend calls this endpoint at all, so granting it would be
    inventing a feature rather than preserving one. A treatment relationship
    exists here and it still does not open presence.
    """
    from app.models.appointment import AppointmentStatus

    await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    res = await client.get(
        f"/users/{auth_doctor['user'].id}/presence",
        headers=auth_patient["headers"],
    )

    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_a_doctor_cannot_inspect_a_colleague(
    client, db, default_clinic, auth_doctor, auth_receptionist
):
    """Doctors get themselves only — no UI needs more."""

    res = await client.get(
        f"/users/{auth_receptionist['user'].id}/presence",
        headers=auth_doctor["headers"],
    )

    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_unknown_id_is_indistinguishable_from_another_clinics_user(
    client, db, auth_admin, second_clinic_receptionist
):
    """6. NO EXISTENCE ORACLE. If an unknown id answered differently from a real
    id outside the caller's clinic, probing would enumerate the user table."""

    unknown = await client.get(
        f"/users/{UNKNOWN_USER_ID}/presence", headers=auth_admin["headers"]
    )
    other = await client.get(
        f"/users/{second_clinic_receptionist.id}/presence",
        headers=auth_admin["headers"],
    )

    assert unknown.status_code == other.status_code, (
        "an unknown id is distinguishable from a real one, which enumerates users"
    )
    assert unknown.json() == other.json()


# ---------------------------------------------------------------------------
# Finding 6 — notification analytics
# ---------------------------------------------------------------------------

NOTIFICATION_ANALYTICS = "/admin/analytics/notifications"
NOTIFICATION_ANALYTICS_DAILY = "/admin/analytics/notifications/daily"


@pytest.mark.asyncio
async def test_super_admin_may_read_notification_analytics(
    client, db, auth_super_admin
):
    """1. Platform telemetry belongs to the platform role."""

    res = await client.get(
        NOTIFICATION_ANALYTICS, headers=auth_super_admin["headers"]
    )

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_clinic_admin_cannot_read_notification_analytics(
    client, db, auth_admin
):
    """2. THE CORE PROPERTY. These totals span every tenant."""

    res = await client.get(NOTIFICATION_ANALYTICS, headers=auth_admin["headers"])

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_super_admin_may_read_daily_notification_volume(
    client, db, auth_super_admin
):
    """3. Same rule on the daily series."""

    res = await client.get(
        NOTIFICATION_ANALYTICS_DAILY, headers=auth_super_admin["headers"]
    )

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_clinic_admin_cannot_read_daily_notification_volume(
    client, db, auth_admin
):
    """3b."""

    res = await client.get(
        NOTIFICATION_ANALYTICS_DAILY, headers=auth_admin["headers"]
    )

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_notification_analytics_response_shape_is_unchanged(
    client, db, auth_super_admin
):
    """4. Only the gate moves; the calculation and its shape stay as they are."""

    res = await client.get(
        NOTIFICATION_ANALYTICS, headers=auth_super_admin["headers"]
    )

    assert res.status_code == 200, res.text
    body = res.json()

    for key in (
        "total_notifications",
        "push_delivered",
        "email_delivered",
        "failed",
        "push_success_rate",
        "email_success_rate",
        "failure_rate",
    ):
        assert key in body, f"analytics response lost the {key!r} field"
