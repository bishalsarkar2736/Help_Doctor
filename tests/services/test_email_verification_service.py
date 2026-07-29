import pytest
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.time import UTC
from app.models.email_verification_token import (
    EmailVerificationToken,
)
from app.security.tokens import (
    generate_secure_token,
    hash_token,
)
from app.services.auth_service import (
    send_verification_email,
    verify_email,
)
from app.try_except.exceptions import BadRequestError


@pytest.mark.asyncio
async def test_send_verification_email(
    db,
    user,
    monkeypatch,
):
    async def fake_send_email_verification_email(**kwargs):
        return None

    monkeypatch.setattr(
        "app.services.auth_service.send_email_verification_email",
        fake_send_email_verification_email,
    )

    response = await send_verification_email(
        db=db,
        user=user,
    )

    assert response["message"] == (
        "Verification email sent successfully."
    )

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
        )
    )

    token = result.scalar_one_or_none()

    assert token is not None
    assert token.used is False


@pytest.mark.asyncio
async def test_send_verification_email_already_verified(
    db,
    user,
):
    user.is_email_verified = True

    with pytest.raises(BadRequestError):
        await send_verification_email(
            db=db,
            user=user,
        )


@pytest.mark.asyncio
async def test_verify_email_success(
    db,
    user,
):
    token = generate_secure_token()

    verification = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC)
        + timedelta(hours=24),
    )

    db.add(verification)

    await db.flush()

    response = await verify_email(
        db=db,
        token=token,
    )

    assert response["message"] == (
        "Email verified successfully."
    )

    assert user.is_email_verified is True
    assert verification.used is True


@pytest.mark.asyncio
async def test_verify_email_invalid_token(
    db,
):
    with pytest.raises(BadRequestError):
        await verify_email(
            db=db,
            token="invalid-token",
        )


@pytest.mark.asyncio
async def test_verify_email_expired_token(
    db,
    user,
):
    token = generate_secure_token()

    verification = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC)
        - timedelta(minutes=1),
    )

    db.add(verification)

    await db.flush()

    with pytest.raises(BadRequestError):
        await verify_email(
            db=db,
            token=token,
        )


@pytest.mark.asyncio
async def test_verify_email_used_token(
    db,
    user,
):
    token = generate_secure_token()

    verification = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC)
        + timedelta(hours=24),
        used=True,
    )

    db.add(verification)

    await db.flush()

    with pytest.raises(BadRequestError):
        await verify_email(
            db=db,
            token=token,
        )