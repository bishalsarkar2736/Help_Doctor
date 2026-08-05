import uuid
import pytest
from sqlalchemy import select

from app.models.user import User, UserRole
from app.models.email_verification_token import EmailVerificationToken


@pytest.mark.asyncio
async def test_register_issues_verification_token(client, db):
    email = f"newpat-{uuid.uuid4()}@test.com"

    res = await client.post(
        "/auth/register",
        json={
            "email": email,
            "full_name": "New Patient",
            "password": "secret123",
            "accepted_terms_version": "2026-08-01",
            "accepted_privacy_version": "2026-08-01",
            "role": "patient",
        },
    )
    assert res.status_code == 201

    user = await db.scalar(select(User).where(User.email == email))
    token = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    assert token is not None  # verification email was issued on signup


@pytest.mark.asyncio
async def test_resend_verification_for_unverified_user(client, db):
    email = f"unv-{uuid.uuid4()}@test.com"
    user = User(
        email=email,
        full_name="Unverified",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
        is_email_verified=False,
    )
    db.add(user)
    await db.flush()

    res = await client.post("/auth/resend-verification", json={"email": email})
    assert res.status_code == 200
    assert "message" in res.json()

    token = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    assert token is not None


@pytest.mark.asyncio
async def test_resend_verification_generic_for_unknown_email(client):
    res = await client.post(
        "/auth/resend-verification",
        json={"email": f"nobody-{uuid.uuid4()}@test.com"},
    )
    # No enumeration: same 200 + generic message.
    assert res.status_code == 200
    assert "message" in res.json()


@pytest.mark.asyncio
async def test_resend_verification_noop_for_verified_user(client, db):
    email = f"ver-{uuid.uuid4()}@test.com"
    user = User(
        email=email,
        full_name="Verified",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    await db.flush()

    res = await client.post("/auth/resend-verification", json={"email": email})
    assert res.status_code == 200

    token = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    assert token is None  # already verified → nothing issued
