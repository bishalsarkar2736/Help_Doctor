"""Two admin listings that had no tenant filter at all.

WHAT WAS WRONG
Both endpoints are ADMIN-only, and both treated "is an admin" as sufficient
without asking *which clinic's* admin. Neither needed enumeration: one call
returned other tenants' rows.

    GET /admin/audit    select(Appointment).where(cancelled_by.isnot(None))
                        — no clinic filter, no response model, so every column
                          of every cancelled appointment on the platform was
                          serialised: patient_id, doctor_id, cancel_reason,
                          consultation_fee, notes, queue timestamps.

    GET /admin/doctors  a join of Doctor and User with limit/offset and no
                        WHERE clause of any kind — every doctor on the
                        platform, including other clinics' emails and the
                        rejection_reason a rival admin wrote.

WHY THE DOCTOR RULE IS NOT SIMPLY "MY CLINIC"
A doctor applies before any clinic has accepted them, so unassigned applicants
(clinic_id IS NULL) must stay visible — that list is how an admin finds someone
to approve. The rule is therefore the same one list_documents_for_admin and
approve_doctor already use: mine, or nobody's yet.

BOTH FAIL CLOSED ON A CLINIC-LESS ADMIN. Such an account should not exist —
resolve_clinic_id and _searcher_clinic_id both refuse one — and defaulting it
to "everything" is precisely the bug being fixed.
"""

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import Range

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User, UserRole
from app.security.jwt import create_access_token


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _cancelled_appointment(db, *, clinic_id, doctor_id, patient_id, hours=3):
    """A cancelled appointment — the only rows /admin/audit returns."""
    start = utc_now() + timedelta(hours=hours)
    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        clinic_id=clinic_id,
        scheduled_at=start,
        status=AppointmentStatus.CANCELLED,
        time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
        cancelled_by=patient_id,
        cancelled_at=utc_now(),
        cancel_reason="patient could not attend",
        consultation_fee=500,
        notes="internal note that must not leak",
    )
    db.add(appointment)
    await db.flush()
    await db.refresh(appointment)
    return appointment


async def _doctor(db, *, clinic_id, status=DoctorStatus.PENDING, name="Dr Probe"):
    user = User(
        email=f"doc-{uuid.uuid4()}@test.com",
        full_name=name,
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        specialization="Probe",
        experience_years=2,
        bio="probe",
        clinic_id=clinic_id,
        status=status,
    )
    db.add(doctor)
    await db.flush()
    await db.refresh(doctor)
    return doctor


@pytest_asyncio.fixture
async def clinicless_admin(db):
    """An ADMIN with no clinic. Must reach nothing, not everything."""
    user = User(
        email=f"admin-nc-{uuid.uuid4()}@test.com",
        full_name="No Clinic Admin",
        hashed_password="x",
        role=UserRole.ADMIN,
        is_active=True,
        clinic_id=None,
    )
    db.add(user)
    await db.flush()

    token = create_access_token(
        data={"sub": str(user.id), "role": UserRole.ADMIN.value}
    )
    return {"user": user, "headers": {"Authorization": f"Bearer {token}"}}


# ---------------------------------------------------------------------------
# Finding 2 — GET /admin/audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_returns_own_clinics_cancelled_appointment(
    client, db, default_clinic, auth_admin, auth_doctor, patient_user
):
    """A. The allow-case, so the deny-cases below cannot pass by the endpoint
    simply returning nothing."""

    appointment = await _cancelled_appointment(
        db,
        clinic_id=default_clinic.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=patient_user.id,
    )

    res = await client.get("/admin/audit", headers=auth_admin["headers"])

    assert res.status_code == 200, res.text
    assert appointment.id in [row["id"] for row in res.json()]


@pytest.mark.asyncio
async def test_audit_hides_another_clinics_cancelled_appointment(
    client, db, default_clinic, auth_admin, auth_doctor, patient_user,
    second_clinic, other_clinic_doctor, other_clinic_patient,
):
    """B. THE CORE PROPERTY. Clinic B's cancelled appointment must not reach
    clinic A's admin."""

    mine = await _cancelled_appointment(
        db,
        clinic_id=default_clinic.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=patient_user.id,
        hours=4,
    )
    theirs = await _cancelled_appointment(
        db,
        clinic_id=second_clinic.id,
        doctor_id=other_clinic_doctor["doctor"].id,
        patient_id=other_clinic_patient.id,
        hours=5,
    )

    res = await client.get("/admin/audit", headers=auth_admin["headers"])

    assert res.status_code == 200, res.text
    ids = [row["id"] for row in res.json()]

    assert mine.id in ids
    assert theirs.id not in ids, (
        "another clinic's cancelled appointment was disclosed"
    )


@pytest.mark.asyncio
async def test_audit_denies_an_admin_with_no_clinic(
    client, db, default_clinic, auth_doctor, patient_user, clinicless_admin
):
    """C. Fails closed. A clinic-less admin must not fall through to the
    unscoped query."""

    await _cancelled_appointment(
        db,
        clinic_id=default_clinic.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=patient_user.id,
        hours=6,
    )

    res = await client.get("/admin/audit", headers=clinicless_admin["headers"])

    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_audit_large_limit_does_not_reach_another_clinic(
    client, db, default_clinic, auth_admin, auth_doctor, patient_user,
    second_clinic, other_clinic_doctor, other_clinic_patient,
):
    """D. The filter is in the WHERE clause, not an artefact of the page size."""

    theirs = await _cancelled_appointment(
        db,
        clinic_id=second_clinic.id,
        doctor_id=other_clinic_doctor["doctor"].id,
        patient_id=other_clinic_patient.id,
        hours=7,
    )

    res = await client.get(
        "/admin/audit",
        params={"limit": 100, "offset": 0},
        headers=auth_admin["headers"],
    )

    assert res.status_code == 200, res.text
    assert theirs.id not in [row["id"] for row in res.json()]


@pytest.mark.asyncio
async def test_audit_does_not_expose_unrelated_columns(
    client, db, default_clinic, auth_admin, auth_doctor, patient_user
):
    """E. A response model, not the ORM row. `notes` and `consultation_fee`
    have nothing to do with an audit of who cancelled what and when, and were
    serialised only because they exist on the table."""

    await _cancelled_appointment(
        db,
        clinic_id=default_clinic.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=patient_user.id,
        hours=8,
    )

    res = await client.get("/admin/audit", headers=auth_admin["headers"])

    assert res.status_code == 200, res.text
    rows = res.json()
    assert rows, "fixture assumption: at least one cancelled appointment"

    forbidden = {
        "notes",
        "consultation_fee",
        "queue_number",
        "checked_in_at",
        "waiting_started_at",
        "consultation_started_at",
        "time_range",
        "version",
        "reminder_sent",
    }

    leaked = forbidden & set(rows[0])
    assert not leaked, f"audit response exposes unrelated columns: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# Finding 3 — GET /admin/doctors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_doctor_list_includes_own_clinics_doctor(
    client, db, default_clinic, auth_admin
):
    """A. The allow-case."""

    mine = await _doctor(db, clinic_id=default_clinic.id, name="Dr Mine")

    res = await client.get("/admin/doctors", headers=auth_admin["headers"])

    assert res.status_code == 200, res.text
    assert mine.id in [row["id"] for row in res.json()]


@pytest.mark.asyncio
async def test_doctor_list_includes_unassigned_applicants(
    client, db, default_clinic, auth_admin
):
    """B. THE WORKFLOW THIS MUST NOT BREAK. An applicant belongs to no clinic
    until someone approves them, and this list is how they are found."""

    applicant = await _doctor(db, clinic_id=None, name="Dr Applicant")

    res = await client.get("/admin/doctors", headers=auth_admin["headers"])

    assert res.status_code == 200, res.text
    assert applicant.id in [row["id"] for row in res.json()]


@pytest.mark.asyncio
async def test_doctor_list_excludes_another_clinics_doctor(
    client, db, default_clinic, auth_admin, second_clinic
):
    """C. THE CORE PROPERTY."""

    mine = await _doctor(db, clinic_id=default_clinic.id, name="Dr Mine")
    theirs = await _doctor(
        db, clinic_id=second_clinic.id, status=DoctorStatus.APPROVED,
        name="Dr Theirs",
    )

    res = await client.get("/admin/doctors", headers=auth_admin["headers"])

    assert res.status_code == 200, res.text
    ids = [row["id"] for row in res.json()]

    assert mine.id in ids
    assert theirs.id not in ids, "another clinic's doctor was listed"


@pytest.mark.asyncio
async def test_doctor_list_pagination_still_works(
    client, db, default_clinic, auth_admin
):
    """D. limit/offset survive the tenant filter."""

    for i in range(3):
        await _doctor(db, clinic_id=default_clinic.id, name=f"Dr Page {i}")

    first = await client.get(
        "/admin/doctors", params={"limit": 2, "offset": 0},
        headers=auth_admin["headers"],
    )
    second = await client.get(
        "/admin/doctors", params={"limit": 2, "offset": 2},
        headers=auth_admin["headers"],
    )

    assert first.status_code == 200 and second.status_code == 200
    assert len(first.json()) <= 2

    first_ids = {r["id"] for r in first.json()}
    second_ids = {r["id"] for r in second.json()}
    assert not (first_ids & second_ids), "pages overlap"


@pytest.mark.asyncio
async def test_doctor_list_never_pages_into_another_clinic(
    client, db, default_clinic, auth_admin, second_clinic
):
    """E. Absent at any page size — the filter is in the query, not the page."""

    theirs = [
        await _doctor(db, clinic_id=second_clinic.id, name=f"Dr Theirs {i}")
        for i in range(3)
    ]

    res = await client.get(
        "/admin/doctors", params={"limit": 100, "offset": 0},
        headers=auth_admin["headers"],
    )

    assert res.status_code == 200, res.text
    ids = {row["id"] for row in res.json()}

    for d in theirs:
        assert d.id not in ids


@pytest.mark.asyncio
async def test_doctor_list_denies_an_admin_with_no_clinic(
    client, db, default_clinic, clinicless_admin
):
    """Fails closed rather than degrading to a platform-wide listing."""

    await _doctor(db, clinic_id=default_clinic.id, name="Dr Mine")

    res = await client.get("/admin/doctors", headers=clinicless_admin["headers"])

    assert res.status_code in (403, 404), res.text
