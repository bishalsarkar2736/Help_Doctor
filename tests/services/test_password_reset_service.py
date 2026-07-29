import pytest
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.time import UTC
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken

from app.security.jwt import (
    hash_password,
    verify_password,
)
from app.security.tokens import (
    generate_secure_token,
    hash_token,
)
from app.services.auth_service import (
    forgot_password,
    reset_password,
)
from app.try_except.exceptions import BadRequestError


@pytest.mark.asyncio
async def test_forgot_password_existing_email(
    db,
    user,
):
    response = await forgot_password(
        db=db,
        email=user.email,
    )

    assert response["message"].startswith(
        "If an account exists"
    )

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
        )
    )

    token = result.scalar_one_or_none()

    assert token is not None
    assert token.used is False


@pytest.mark.asyncio
async def test_forgot_password_unknown_email(
    db,
):
    response = await forgot_password(
        db=db,
        email="unknown@test.com",
    )

    assert response["message"].startswith(
        "If an account exists"
    )

    result = await db.execute(
        select(PasswordResetToken)
    )

    assert result.scalars().first() is None



@pytest.mark.asyncio
async def test_reset_password_success(
    db,
    user,
):
    user.hashed_password = hash_password(
        "OldPassword123!"
    )

    token = generate_secure_token()

    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC)
        + timedelta(hours=1),
    )

    refresh = RefreshToken(
        token="refresh-token",
        user_id=user.id,
        expires_at=datetime.now(UTC)
        + timedelta(days=30),
    )

    db.add_all([reset, refresh])

    await db.flush()

    response = await reset_password(
        db=db,
        token=token,
        new_password="NewPassword123!",
    )

    assert response["message"] == (
        "Password has been reset successfully."
    )

    assert verify_password(
        "NewPassword123!",
        user.hashed_password,
    )

    assert reset.used is True
    assert refresh.revoked is True


@pytest.mark.asyncio
async def test_reset_password_invalid_token(
    db,
):
    with pytest.raises(BadRequestError):
        await reset_password(
            db=db,
            token="invalid-token",
            new_password="Password123!",
        )


@pytest.mark.asyncio
async def test_reset_password_expired_token(
    db,
    user,
):
    token = generate_secure_token()

    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC)
        - timedelta(minutes=1),
    )

    db.add(reset)

    await db.flush()

    with pytest.raises(BadRequestError):
        await reset_password(
            db=db,
            token=token,
            new_password="Password123!",
        )


@pytest.mark.asyncio
async def test_reset_password_used_token(
    db,
    user,
):
    token = generate_secure_token()

    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC)
        + timedelta(hours=1),
        used=True,
    )

    db.add(reset)

    await db.flush()

    with pytest.raises(BadRequestError):
        await reset_password(
            db=db,
            token=token,
            new_password="Password123!",
        )


@pytest.mark.asyncio
async def test_reset_password_updates_password(
    db,
    user,
):
    user.hashed_password = hash_password(
        "OldPassword123!"
    )

    token = generate_secure_token()

    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            + timedelta(hours=1),
        )
    )

    await db.flush()

    await reset_password(
        db=db,
        token=token,
        new_password="BrandNewPassword123!",
    )

    assert verify_password(
        "BrandNewPassword123!",
        user.hashed_password,
    )

@pytest.mark.asyncio
async def test_reset_password_revokes_refresh_tokens(
    db,
    user,
):
    token = generate_secure_token()

    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            + timedelta(hours=1),
        )
    )

    refresh1 = RefreshToken(
        token="refresh1",
        user_id=user.id,
        expires_at=datetime.now(UTC)
        + timedelta(days=30),
    )

    refresh2 = RefreshToken(
        token="refresh2",
        user_id=user.id,
        expires_at=datetime.now(UTC)
        + timedelta(days=30),
    )

    db.add_all([refresh1, refresh2])

    user.hashed_password = hash_password("OldPassword123!")

    await db.flush()

    await reset_password(
        db=db,
        token=token,
        new_password="Password123!",
    )

    assert refresh1.revoked is True
    assert refresh2.revoked is True