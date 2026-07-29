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
