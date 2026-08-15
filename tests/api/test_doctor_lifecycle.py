import uuid
import pytest
import pytest_asyncio

from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus


async def _make_doctor(db, clinic_id=None, status=DoctorStatus.PENDING):
    user = User(
        email=f"doc-{uuid.uuid4()}@test.com",
        full_name="Dr Test",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        specialization="Cardiology",
        experience_years=4,
        bio="Test",
        clinic_id=clinic_id,
        status=status,
    )
    db.add(doctor)
    await db.flush()
    await db.refresh(doctor)
    return doctor


@pytest.mark.asyncio
async def test_approve_doctor(client, db, default_clinic, auth_admin):
    doctor = await _make_doctor(db)  # PENDING, unassigned

    res = await client.post(
        f"/admin/doctors/{doctor.id}/approve",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "APPROVED"

    await db.refresh(doctor)
    assert doctor.status == DoctorStatus.APPROVED
    assert doctor.clinic_id == default_clinic.id
    assert doctor.approved_by == auth_admin["user"].id
    assert doctor.approved_at is not None


@pytest.mark.asyncio
async def test_reject_doctor_records_audit(client, db, default_clinic, auth_admin):
    doctor = await _make_doctor(db, clinic_id=default_clinic.id)

    res = await client.post(
        f"/admin/doctors/{doctor.id}/reject",
        json={"reason": "Incomplete license"},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "REJECTED"

    await db.refresh(doctor)
    assert doctor.status == DoctorStatus.REJECTED
    assert doctor.rejected_by == auth_admin["user"].id
    assert doctor.rejected_at is not None
    assert doctor.rejection_reason == "Incomplete license"


@pytest.mark.asyncio
async def test_suspend_and_reinstate(client, db, default_clinic, auth_admin):
    doctor = await _make_doctor(
        db, clinic_id=default_clinic.id, status=DoctorStatus.APPROVED
    )

    suspend = await client.post(
        f"/admin/doctors/{doctor.id}/suspend",
        headers=auth_admin["headers"],
    )
    assert suspend.status_code == 200
    await db.refresh(doctor)
    assert doctor.status == DoctorStatus.SUSPENDED

    reinstate = await client.post(
        f"/admin/doctors/{doctor.id}/reinstate",
        headers=auth_admin["headers"],
    )
    assert reinstate.status_code == 200
    await db.refresh(doctor)
    assert doctor.status == DoctorStatus.APPROVED


@pytest.mark.asyncio
async def test_suspend_requires_approved(client, db, default_clinic, auth_admin):
    doctor = await _make_doctor(db, clinic_id=default_clinic.id)  # PENDING

    res = await client.post(
        f"/admin/doctors/{doctor.id}/suspend",
        headers=auth_admin["headers"],
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_only_approved_doctors_in_public_directory(
    client, db, default_clinic
):
    approved = await _make_doctor(
        db, clinic_id=default_clinic.id, status=DoctorStatus.APPROVED
    )
    await _make_doctor(db, clinic_id=default_clinic.id, status=DoctorStatus.PENDING)

    res = await client.get("/doctors")
    assert res.status_code == 200
    ids = [d["id"] for d in res.json()]
    assert approved.id in ids
    # Only approved + active doctors are listed.
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_approve_requires_admin(client, db, default_clinic, auth_doctor):
    doctor = await _make_doctor(db)

    res = await client.post(
        f"/admin/doctors/{doctor.id}/approve",
        params={"clinic_id": default_clinic.id},
        headers=auth_doctor["headers"],
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Approval must not capture another clinic's doctor
# ---------------------------------------------------------------------------
#
# THE DEFECT
# approve_doctor looked its subject up by primary key alone and then wrote
#
#     doctor.clinic_id = clinic.id
#
# with no check on the clinic the doctor already belonged to. resolve_clinic_id
# correctly pins the TARGET clinic to the admin's own, so this is not a way to
# write into someone else's tenant — it is the opposite. A clinic admin could
# name any doctor_id and pull that doctor INTO their clinic, and doctor ids are
# sequential, so the whole platform was enumerable.
#
# Its three siblings in the same service all guard this boundary already:
# reject_doctor checks it explicitly, and suspend_doctor and reinstate_doctor
# filter Doctor.clinic_id == admin.clinic_id in the query. The one function that
# WRITES clinic_id was the one that did not.
#
# WHY IT MATTERS BEYOND THE ROW
# Doctor.clinic_id is an authorization input, not a label. may_subscribe gates
# doctor_queue:{id} on it, GET /appointments/queue?doctor_id= authorizes with
# it, _searcher_clinic_id resolves a doctor's PHI scope from it, and
# book_appointment stamps new appointments with it. Capturing the row
# manufactures all of those at once.


@pytest.mark.asyncio
async def test_cannot_approve_another_clinics_doctor(
    client, db, default_clinic, second_clinic, auth_admin
):
    """THE CORE PROPERTY. Clinic A's admin may not pull clinic B's doctor in."""

    doctor = await _make_doctor(
        db, clinic_id=second_clinic.id, status=DoctorStatus.APPROVED
    )

    res = await client.post(
        f"/admin/doctors/{doctor.id}/approve",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )

    assert res.status_code == 403, res.text

    await db.refresh(doctor)
    assert doctor.clinic_id == second_clinic.id, (
        "the doctor was moved into the approving admin's clinic"
    )


@pytest.mark.asyncio
async def test_cannot_capture_another_clinics_pending_doctor(
    client, db, default_clinic, second_clinic, auth_admin
):
    """Still refused when the target is only PENDING at the other clinic — the
    rule is about whose doctor it is, not what state they are in."""

    doctor = await _make_doctor(
        db, clinic_id=second_clinic.id, status=DoctorStatus.PENDING
    )

    res = await client.post(
        f"/admin/doctors/{doctor.id}/approve",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )

    assert res.status_code == 403, res.text

    await db.refresh(doctor)
    assert doctor.clinic_id == second_clinic.id
    assert doctor.status == DoctorStatus.PENDING, (
        "a refused approval must not have changed the doctor's status"
    )


@pytest.mark.asyncio
async def test_an_unassigned_applicant_can_still_be_approved(
    client, db, default_clinic, auth_admin
):
    """THE WORKFLOW THIS MUST NOT BREAK. A doctor applies with no clinic and is
    approved into the one that accepts them — the reason the endpoint exists."""

    doctor = await _make_doctor(db, clinic_id=None)

    res = await client.post(
        f"/admin/doctors/{doctor.id}/approve",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )

    assert res.status_code == 200, res.text

    await db.refresh(doctor)
    assert doctor.clinic_id == default_clinic.id
    assert doctor.status == DoctorStatus.APPROVED


@pytest.mark.asyncio
async def test_a_doctor_of_this_clinic_can_be_reapproved(
    client, db, default_clinic, auth_admin
):
    """Re-approval within the admin's own clinic stays allowed: it is how a
    rejected doctor is reinstated, and it clears the rejection fields."""

    doctor = await _make_doctor(
        db, clinic_id=default_clinic.id, status=DoctorStatus.REJECTED
    )

    res = await client.post(
        f"/admin/doctors/{doctor.id}/approve",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )

    assert res.status_code == 200, res.text

    await db.refresh(doctor)
    assert doctor.clinic_id == default_clinic.id
    assert doctor.status == DoctorStatus.APPROVED
    assert doctor.rejected_at is None
    assert doctor.rejection_reason is None
