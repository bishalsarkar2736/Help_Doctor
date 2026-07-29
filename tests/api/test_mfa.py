import uuid

import pyotp
import pytest

from app.models.user import User, UserRole
from app.security.jwt import hash_password
from app.services.auth_service import authentication_user
from app.try_except.exceptions import UnauthorizedError


# ---- enrollment via HTTP (uses the admin token; no password needed) ----

@pytest.mark.asyncio
async def test_mfa_setup_and_enable(client, db, auth_admin):
    res = await client.post("/auth/mfa/setup", headers=auth_admin["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    secret = body["secret"]
    assert body["otpauth_uri"].startswith("otpauth://")
    assert body["qr_data_uri"].startswith("data:image/png;base64,")

    code = pyotp.TOTP(secret).now()
    res = await client.post(
        "/auth/mfa/enable", json={"code": code}, headers=auth_admin["headers"]
    )
    assert res.status_code == 200, res.text
    assert res.json()["mfa_enabled"] is True

    await db.refresh(auth_admin["user"])
    assert auth_admin["user"].mfa_enabled is True


@pytest.mark.asyncio
async def test_mfa_enable_rejects_bad_code(client, auth_admin):
    await client.post("/auth/mfa/setup", headers=auth_admin["headers"])
    res = await client.post(
        "/auth/mfa/enable", json={"code": "000000"}, headers=auth_admin["headers"]
    )
    assert res.status_code == 400


# ---- login enforcement (service level: real password hash) ----

async def _mfa_user(db):
    secret = pyotp.random_base32()
    user = User(
        email=f"mfa-{uuid.uuid4()}@t.com",
        full_name="MFA Staff",
        hashed_password=hash_password("Str0ngPass1"),
        role=UserRole.DOCTOR,
        is_active=True,
        is_email_verified=True,
        mfa_enabled=True,
        mfa_secret=secret,
    )
    db.add(user)
    await db.flush()
    return user, secret


@pytest.mark.asyncio
async def test_login_requires_mfa_code(db):
    user, _secret = await _mfa_user(db)
    with pytest.raises(UnauthorizedError, match="MFA_REQUIRED"):
        await authentication_user(db, user.email, "Str0ngPass1", mfa_code=None)


@pytest.mark.asyncio
async def test_login_rejects_wrong_mfa_code(db):
    user, _secret = await _mfa_user(db)
    with pytest.raises(UnauthorizedError, match="Invalid MFA code"):
        await authentication_user(db, user.email, "Str0ngPass1", mfa_code="000000")


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_mfa_code(db):
    user, secret = await _mfa_user(db)
    code = pyotp.TOTP(secret).now()
    tokens = await authentication_user(db, user.email, "Str0ngPass1", mfa_code=code)
    assert tokens is not None
