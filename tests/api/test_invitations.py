import uuid
import pytest

from sqlalchemy import select

from app.models.user import User, UserRole
from app.models.clinic import Clinic
from app.models.invitation import Invitation, InvitationStatus


@pytest.fixture
def capture_invite_email(monkeypatch):
    """Capture the raw token that would have been emailed."""
    captured = {}

    async def fake_send_invitation_email(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.services.invitation_service.send_invitation_email",
        fake_send_invitation_email,
    )
    return captured


def _new_email() -> str:
    return f"invitee-{uuid.uuid4()}@test.com"


# ----------------------------- CREATE / RBAC -----------------------------

@pytest.mark.asyncio
async def test_super_admin_invites_clinic_admin(
    client, default_clinic, auth_super_admin, capture_invite_email
):
    email = _new_email()
    res = await client.post(
        "/invitations",
        json={"email": email, "role": "admin", "clinic_id": default_clinic.id},
        headers=auth_super_admin["headers"],
    )

    assert res.status_code == 201
    body = res.json()
    assert body["email"] == email
    assert body["role"] == "admin"
    assert body["clinic_id"] == default_clinic.id
    assert body["status"] == "PENDING"
    assert capture_invite_email.get("token")  # token was generated/emailed


@pytest.mark.asyncio
async def test_clinic_admin_invites_receptionist_and_doctor(
    client, default_clinic, auth_admin, capture_invite_email
):
    for role in ("receptionist", "doctor"):
        res = await client.post(
            "/invitations",
            json={
                "email": _new_email(),
                "role": role,
                "clinic_id": default_clinic.id,
            },
            headers=auth_admin["headers"],
        )
        assert res.status_code == 201, res.text
        assert res.json()["role"] == role


@pytest.mark.asyncio
async def test_clinic_admin_cannot_invite_admin(
    client, default_clinic, auth_admin, capture_invite_email
):
    res = await client.post(
        "/invitations",
        json={"email": _new_email(), "role": "admin", "clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_cannot_invite_receptionist(
    client, default_clinic, auth_super_admin, capture_invite_email
):
    res = await client.post(
        "/invitations",
        json={"email": _new_email(), "role": "receptionist", "clinic_id": default_clinic.id},
        headers=auth_super_admin["headers"],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_clinic_admin_cannot_invite_to_other_clinic(
    client, db, default_clinic, auth_admin, capture_invite_email
):
    other = Clinic(name="Other Clinic", address="X", phone="019", email="o@t.com")
    db.add(other)
    await db.flush()

    res = await client.post(
        "/invitations",
        json={"email": _new_email(), "role": "doctor", "clinic_id": other.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_invite_existing_email_rejected(
    client, db, default_clinic, auth_admin, capture_invite_email
):
    existing = User(
        email="already@test.com",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(existing)
    await db.flush()

    res = await client.post(
        "/invitations",
        json={"email": "already@test.com", "role": "doctor", "clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 400


# ----------------------------- PREVIEW / ACCEPT -----------------------------

@pytest.mark.asyncio
async def test_preview_and_accept_invitation(
    client, db, default_clinic, auth_admin, capture_invite_email
):
    email = _new_email()

    create = await client.post(
        "/invitations",
        json={"email": email, "role": "receptionist", "clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert create.status_code == 201
    token = capture_invite_email["token"]

    # Preview (public)
    preview = await client.get("/invitations/preview", params={"token": token})
    assert preview.status_code == 200
    assert preview.json()["email"] == email
    assert preview.json()["clinic_name"] == default_clinic.name

    # Accept (public) → creates a verified user bound to the clinic
    accept = await client.post(
        "/invitations/accept",
        json={"token": token, "full_name": "New Staff", "password": "secret123"},
    )
    assert accept.status_code == 200, accept.text
    user_id = accept.json()["user_id"]

    created = await db.get(User, user_id)
    assert created.role == UserRole.RECEPTIONIST
    assert created.clinic_id == default_clinic.id
    assert created.is_email_verified is True

    inv = await db.scalar(select(Invitation).where(Invitation.email == email))
    assert inv.status == InvitationStatus.ACCEPTED
    assert inv.accepted_user_id == user_id


@pytest.mark.asyncio
async def test_accepted_user_can_login(
    client, default_clinic, auth_admin, capture_invite_email
):
    email = _new_email()
    await client.post(
        "/invitations",
        json={"email": email, "role": "doctor", "clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    token = capture_invite_email["token"]

    await client.post(
        "/invitations/accept",
        json={"token": token, "full_name": "Dr Test", "password": "secret123"},
    )

    login = await client.post(
        "/auth/login-json",
        json={"email": email, "password": "secret123"},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


@pytest.mark.asyncio
async def test_accept_invalid_token(client):
    res = await client.post(
        "/invitations/accept",
        json={"token": "not-a-real-token", "full_name": "X", "password": "secret123"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_revoked_invitation_cannot_be_accepted(
    client, default_clinic, auth_admin, capture_invite_email
):
    create = await client.post(
        "/invitations",
        json={"email": _new_email(), "role": "doctor", "clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    invitation_id = create.json()["id"]
    token = capture_invite_email["token"]

    revoke = await client.post(
        f"/invitations/{invitation_id}/revoke",
        headers=auth_admin["headers"],
    )
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "REVOKED"

    accept = await client.post(
        "/invitations/accept",
        json={"token": token, "full_name": "X", "password": "secret123"},
    )
    assert accept.status_code == 400


# ----------------------------- LOGIN EMAIL VERIFICATION -----------------------------

@pytest.mark.asyncio
async def test_login_requires_verified_email(client):
    email = _new_email()

    reg = await client.post(
        "/auth/register",
        json={
            "email": email,
            "full_name": "Unverified Patient",
            "password": "secret123",
            "role": "patient",
        },
    )
    assert reg.status_code == 201

    # Unverified → login blocked.
    login = await client.post(
        "/auth/login-json",
        json={"email": email, "password": "secret123"},
    )
    assert login.status_code == 403
