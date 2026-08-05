"""Registration OTP email verification.

A 6-digit code is brute-forceable (10^6), so these tests pin the two controls
that make it safe: verification is scoped to the requesting account, and a code
locks out after MAX_OTP_ATTEMPTS wrong guesses.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.limiter import limiter
from app.models.user import User
from app.models.email_verification_token import EmailVerificationToken
from app.security.tokens import generate_otp, hash_token
from app.security.jwt import verify_password
from app.services.auth_service import MAX_OTP_ATTEMPTS


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """These tests register/verify more times than the per-IP limits allow.

    The limiter uses in-process memory shared across the whole test session, so
    reset it per test — otherwise results depend on execution order.
    """
    limiter.reset()
    yield
    limiter.reset()


def _email() -> str:
    return f"otp-{uuid.uuid4().hex[:10]}@test.com"


async def _register(client, email: str):
    """Register a user; capture the OTP that would have been emailed."""
    sent = {}

    async def _capture(*, email, code, expires_minutes):
        sent["code"] = code

    with patch(
        "app.services.auth_service.send_email_verification_otp",
        AsyncMock(side_effect=_capture),
    ):
        res = await client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "Test12345",
                "accepted_terms_version": "2026-08-01",
                "accepted_privacy_version": "2026-08-01",
                "full_name": "OTP User",
                "role": "patient",
            },
        )
    assert res.status_code == 201, res.text
    return sent.get("code")


# ---- generator ----

def test_generate_otp_is_six_digits_and_zero_padded():
    for _ in range(200):
        code = generate_otp()
        assert len(code) == 6
        assert code.isdigit()


# ---- happy path ----

@pytest.mark.asyncio
async def test_register_sends_otp_and_verifies(client, db):
    email = _email()
    code = await _register(client, email)
    assert code and len(code) == 6

    user = await db.scalar(select(User).where(User.email == email))
    assert user.is_email_verified is False

    res = await client.post("/auth/verify-otp", json={"email": email, "code": code})
    assert res.status_code == 200, res.text

    await db.refresh(user)
    assert user.is_email_verified is True


# ---- security ----

@pytest.mark.asyncio
async def test_wrong_code_is_rejected_and_counts_an_attempt(client, db):
    email = _email()
    code = await _register(client, email)

    wrong = "000000" if code != "000000" else "111111"
    res = await client.post("/auth/verify-otp", json={"email": email, "code": wrong})
    assert res.status_code == 400

    user = await db.scalar(select(User).where(User.email == email))
    assert user.is_email_verified is False

    # Read the value straight from the DB. The endpoint raises after
    # incrementing, so this only holds if the increment was COMMITTED — a
    # flush() alone gets rolled back by the request teardown.
    persisted = await db.scalar(
        select(EmailVerificationToken.attempts).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    assert persisted == 1, "attempt counter must survive the raised error"


@pytest.mark.asyncio
async def test_code_locks_out_after_max_attempts(client, db):
    email = _email()
    code = await _register(client, email)
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(MAX_OTP_ATTEMPTS):
        await client.post("/auth/verify-otp", json={"email": email, "code": wrong})

    # Even the CORRECT code is refused once the attempt cap is hit.
    res = await client.post("/auth/verify-otp", json={"email": email, "code": code})
    assert res.status_code == 400
    assert "too many" in res.text.lower()

    user = await db.scalar(select(User).where(User.email == email))
    assert user.is_email_verified is False


@pytest.mark.asyncio
async def test_code_is_scoped_to_its_own_account(client, db):
    """A code issued for user A must not verify user B."""
    email_a, email_b = _email(), _email()
    code_a = await _register(client, email_a)
    await _register(client, email_b)

    res = await client.post("/auth/verify-otp", json={"email": email_b, "code": code_a})
    assert res.status_code == 400

    user_b = await db.scalar(select(User).where(User.email == email_b))
    assert user_b.is_email_verified is False


@pytest.mark.asyncio
async def test_otp_is_not_stored_in_plaintext(client, db):
    email = _email()
    code = await _register(client, email)

    user = await db.scalar(select(User).where(User.email == email))
    row = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    assert row.token_hash != code

    # Stored under a KDF, NOT a bare digest. A SHA-256 of a 6-digit code has
    # only ~20 bits behind it and is reversible in under a second, so anyone
    # who can read this table would recover every outstanding code.
    assert row.token_hash != hash_token(code)
    assert row.token_hash.startswith("$argon2")
    assert verify_password(code, row.token_hash)


@pytest.mark.asyncio
async def test_resend_issues_a_new_code_and_invalidates_the_old(client, db):
    email = _email()
    old_code = await _register(client, email)

    sent = {}

    async def _capture(*, email, code, expires_minutes):
        sent["code"] = code

    with patch(
        "app.services.auth_service.send_email_verification_otp",
        AsyncMock(side_effect=_capture),
    ):
        res = await client.post("/auth/resend-verification", json={"email": email})
    assert res.status_code == 200

    new_code = sent["code"]
    # The superseded code no longer works.
    if new_code != old_code:
        res = await client.post(
            "/auth/verify-otp", json={"email": email, "code": old_code}
        )
        assert res.status_code == 400

    res = await client.post("/auth/verify-otp", json={"email": email, "code": new_code})
    assert res.status_code == 200
