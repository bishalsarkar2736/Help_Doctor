from datetime import datetime, timedelta
import pytest
from app.core.time import UTC
from app.models.password_reset_token import PasswordResetToken
from app.security.jwt import hash_password
from app.security.tokens import (
    generate_secure_token,
    hash_token,
)


@pytest.mark.asyncio
async def test_forgot_password_api_existing_email(
    client,
    user,
    monkeypatch,
):
    """
    Existing email returns success.
    """

    async def fake_send_password_reset_email(**kwargs):
        return None

    monkeypatch.setattr(
        "app.services.auth_service.send_password_reset_email",
        fake_send_password_reset_email,
    )

    response = await client.post(
        "/auth/forgot-password",
        json={
            "email": user.email,
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "message": (
            "If an account exists, a password reset email has been sent."
        )
    }


@pytest.mark.asyncio
async def test_forgot_password_api_unknown_email(
    client,
):
    """
    Unknown email should still return success.
    """

    response = await client.post(
        "/auth/forgot-password",
        json={
            "email": "unknown@test.com",
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "message": (
            "If an account exists, a password reset email has been sent."
        )
    }


@pytest.mark.asyncio
async def test_reset_password_api_success(
    client,
    db,
    user,
):
    user.hashed_password = hash_password("OldPassword123!")

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

    response = await client.post(
        "/auth/reset-password",
        json={
            "token": token,
            "new_password": "NewPassword123!",
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "message": "Password has been reset successfully."
    }


@pytest.mark.asyncio
async def test_reset_password_api_invalid_token(
    client,
):
    response = await client.post(
        "/auth/reset-password",
        json={
            "token": "invalid-token",
            "new_password": "Password123!",
        },
    )

 
    assert response.status_code == 400

    assert response.json()["error"]["type"] == "BadRequestError"
    assert response.json()["error"]["message"] == "Invalid reset token"


@pytest.mark.asyncio
async def test_reset_password_api_expired_token(
    client,
    db,
    user,
):
    user.hashed_password = hash_password("OldPassword123!")

    token = generate_secure_token()

    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            - timedelta(minutes=1),
        )
    )

    await db.flush()

    response = await client.post(
        "/auth/reset-password",
        json={
            "token": token,
            "new_password": "Password123!",
        },
    )

    assert response.status_code == 400

    assert response.json()["error"]["type"] == "BadRequestError"
    assert response.json()["error"]["message"] == "Reset token has expired"