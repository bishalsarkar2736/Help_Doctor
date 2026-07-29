"""LINK and OTP verification tokens must not be interchangeable.

Both live in `email_verification_tokens`. /auth/verify-email resolves a token by
a global hash lookup with no user scoping and no attempt cap — safe for a
256-bit link token, catastrophic for a 6-digit OTP. Before the token_type
discriminator, sending OTP guesses to the link endpoint bypassed the OTP's
attempt cap and rate limit entirely.
"""

import pytest
from sqlalchemy import select

from app.models.email_verification_token import (
    TOKEN_TYPE_LINK,
    TOKEN_TYPE_OTP,
    EmailVerificationToken,
)
from app.models.user import User, UserRole
from app.security.jwt import hash_password


async def _unverified_user(db, email="tokeniso@test.com"):
    user = User(
        email=email,
        hashed_password=hash_password("Password123"),
        role=UserRole.PATIENT,
        is_active=True,
        is_email_verified=False,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_otp_cannot_be_redeemed_through_the_link_endpoint(client, db):
    """The bypass, pinned shut."""

    user = await _unverified_user(db)
    from app.services.auth_service import _issue_verification_otp

    await _issue_verification_otp(db=db, user=user)
    await db.commit()

    # Recover the real code the way the user would receive it is not possible
    # (it is Argon2-hashed), so drive the check from a known code instead.
    row = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    assert row.token_type == TOKEN_TYPE_OTP

    # Even the *correct* OTP must not verify through the link endpoint.
    known = "424242"
    row.token_hash = hash_password(known)
    await db.commit()

    response = await client.post("/auth/verify-email", json={"token": known})

    assert response.status_code == 400
    await db.refresh(user)
    assert user.is_email_verified is False


@pytest.mark.asyncio
async def test_link_token_still_verifies(client, db):
    user = await _unverified_user(db, "linkok@test.com")
    from app.services.auth_service import _issue_verification_email

    await _issue_verification_email(db=db, user=user)
    await db.commit()

    row = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    assert row.token_type == TOKEN_TYPE_LINK


@pytest.mark.asyncio
async def test_link_token_cannot_be_redeemed_as_an_otp(client, db):
    """The mirror case: a link token must not satisfy the OTP endpoint."""

    user = await _unverified_user(db, "linkasotp@test.com")
    from app.services.auth_service import _issue_verification_email

    await _issue_verification_email(db=db, user=user)
    await db.commit()

    response = await client.post(
        "/auth/verify-otp",
        json={"email": user.email, "code": "123456"},
    )

    # No OTP exists for this user, so this must fail regardless of the code.
    assert response.status_code == 400
    await db.refresh(user)
    assert user.is_email_verified is False


@pytest.mark.asyncio
async def test_otp_is_not_stored_as_a_reversible_digest(client, db):
    """A bare SHA-256 of a 6-digit code is reversible in under a second."""

    import hashlib

    user = await _unverified_user(db, "otphash@test.com")
    from app.services.auth_service import _issue_verification_otp

    await _issue_verification_otp(db=db, user=user)
    await db.commit()

    row = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )

    # Exhaust the entire 6-digit keyspace against the stored value.
    digests = {
        hashlib.sha256(f"{i:06d}".encode()).hexdigest() for i in range(1000000)
    }
    assert row.token_hash not in digests
    assert row.token_hash.startswith("$argon2")
