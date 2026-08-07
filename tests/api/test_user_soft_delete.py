import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.models.appointment import Appointment, AppointmentStatus
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.security.tokens import hash_token


@pytest.mark.asyncio
async def test_hard_delete_is_refused_when_clinical_records_exist(
    db, auth_patient, auth_doctor, appointment_factory
):
    """The whole point: the database must refuse to destroy medical history."""

    patient = auth_patient["user"]
    await appointment_factory(
        patient_id=patient.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )
    await db.flush()

    with pytest.raises(IntegrityError):
        await db.execute(delete(User).where(User.id == patient.id))
        await db.flush()

    await db.rollback()


@pytest.mark.asyncio
async def test_soft_delete_retains_appointments(
    client, db, auth_admin, auth_doctor, appointment_factory, default_clinic
):
    staff = User(
        email="leaver@test.com",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(staff)
    await db.flush()

    await appointment_factory(
        patient_id=staff.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )
    await db.flush()

    response = await client.delete(
        f"/admin/users/{staff.id}", headers=auth_admin["headers"]
    )
    assert response.status_code == 200

    await db.refresh(staff)
    assert staff.deleted_at is not None
    assert staff.is_active is False

    # The medical record survived the deletion.
    surviving = await db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.patient_id == staff.id)
    )
    assert surviving == 1


@pytest.mark.asyncio
async def test_soft_delete_revokes_refresh_tokens(
    client, db, auth_admin, default_clinic
):
    staff = User(
        email="sessions@test.com",
        hashed_password="x",
        role=UserRole.RECEPTIONIST,
        is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(staff)
    await db.flush()

    db.add(
        RefreshToken(
            user_id=staff.id,
            token_hash=hash_token("live-token"),
            revoked=False,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    await db.flush()

    await client.delete(
        f"/admin/users/{staff.id}", headers=auth_admin["headers"]
    )

    still_live = await db.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(
            RefreshToken.user_id == staff.id,
            RefreshToken.revoked.is_(False),
        )
    )
    assert still_live == 0


@pytest.mark.asyncio
async def test_deleted_user_cannot_log_in(client, db, auth_admin, default_clinic):
    from app.security.jwt import hash_password

    staff = User(
        email="cantlogin@test.com",
        hashed_password=hash_password("Password123"),
        role=UserRole.RECEPTIONIST,
        is_active=True,
        is_email_verified=True,
        clinic_id=default_clinic.id,
    )
    db.add(staff)
    await db.flush()

    ok = await client.post(
        "/auth/login",
        data={"username": "cantlogin@test.com", "password": "Password123"},
    )
    assert ok.status_code == 200

    await client.delete(
        f"/admin/users/{staff.id}", headers=auth_admin["headers"]
    )

    blocked = await client.post(
        "/auth/login",
        data={"username": "cantlogin@test.com", "password": "Password123"},
    )
    assert blocked.status_code == 403
    assert "deleted" in blocked.text.lower()


@pytest.mark.asyncio
async def test_deleted_user_cannot_be_reactivated(
    client, db, auth_admin, default_clinic
):
    """Toggling is_active must not resurrect a deleted account."""

    staff = User(
        email="zombie@test.com",
        hashed_password="x",
        role=UserRole.RECEPTIONIST,
        is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(staff)
    await db.flush()

    await client.delete(
        f"/admin/users/{staff.id}", headers=auth_admin["headers"]
    )

    response = await client.post(
        f"/admin/users/{staff.id}/toggle-active",
        headers=auth_admin["headers"],
    )
    assert response.status_code == 400

    await db.refresh(staff)
    assert staff.is_active is False


@pytest.mark.asyncio
async def test_admin_cannot_delete_themselves(client, auth_admin):
    response = await client.delete(
        f"/admin/users/{auth_admin['user'].id}", headers=auth_admin["headers"]
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_cannot_delete_another_clinics_user(
    client, db, auth_admin, another_patient_user
):
    another_patient_user.clinic_id = None
    await db.flush()

    response = await client.delete(
        f"/admin/users/{another_patient_user.id}",
        headers=auth_admin["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_deleting_twice_is_rejected(client, db, auth_admin, default_clinic):
    staff = User(
        email="twice@test.com",
        hashed_password="x",
        role=UserRole.RECEPTIONIST,
        is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(staff)
    await db.flush()

    first = await client.delete(
        f"/admin/users/{staff.id}", headers=auth_admin["headers"]
    )
    assert first.status_code == 200

    second = await client.delete(
        f"/admin/users/{staff.id}", headers=auth_admin["headers"]
    )
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_deleted_user_hidden_from_admin_roster(
    client, db, auth_admin, default_clinic
):
    staff = User(
        email="hidden@test.com",
        hashed_password="x",
        role=UserRole.RECEPTIONIST,
        is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(staff)
    await db.flush()

    before = await client.get("/admin/users", headers=auth_admin["headers"])
    assert any(u["email"] == "hidden@test.com" for u in before.json())

    await client.delete(
        f"/admin/users/{staff.id}", headers=auth_admin["headers"]
    )

    after = await client.get("/admin/users", headers=auth_admin["headers"])
    assert not any(u["email"] == "hidden@test.com" for u in after.json())
