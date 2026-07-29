import pytest
from datetime import datetime, timedelta
from app.core.time import UTC
from app.services.auth_service import change_password
from app.security.jwt import hash_password, verify_password
from app.models.refresh_token import RefreshToken
from app.try_except.exceptions import UnauthorizedError, BadRequestError


@pytest.mark.asyncio
async def test_change_password_success(
    db,
    user,
):
    user.hashed_password = hash_password("OldPassword123!")

    refresh = RefreshToken(
        token="refresh-token",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )

    db.add(refresh)
    await db.flush()

    response = await change_password(
        db=db,
        user=user,
        current_password="OldPassword123!",
        new_password="NewPassword123!",
    )

    assert response["message"] == (
        "Password changed successfully. Please log in again."
    )

    assert verify_password(
        "NewPassword123!",
        user.hashed_password,
    )

    assert refresh.revoked is True


@pytest.mark.asyncio
async def test_change_password_wrong_current_password(
    db,
    user,
):
    user.hashed_password = hash_password("OldPassword123!")

    with pytest.raises(UnauthorizedError):
        await change_password(
            db=db,
            user=user,
            current_password="WrongPassword",
            new_password="NewPassword123!",
        )


@pytest.mark.asyncio
async def test_change_password_same_password(
    db,
    user,
):
    user.hashed_password = hash_password("OldPassword123!")

    with pytest.raises(BadRequestError):
        await change_password(
            db=db,
            user=user,
            current_password="OldPassword123!",
            new_password="OldPassword123!",
        )


@pytest.mark.asyncio
async def test_google_user_cannot_change_password(
    db,
    google_user,
):
    with pytest.raises(BadRequestError):
        await change_password(
            db=db,
            user=google_user,
            current_password="anything",
            new_password="Password123!",
        )