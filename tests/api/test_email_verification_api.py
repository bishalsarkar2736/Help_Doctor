from datetime import datetime, timedelta

import pytest

from app.core.time import UTC
from app.models.email_verification_token import (
    EmailVerificationToken,
)
from app.security.tokens import (
    generate_secure_token,
    hash_token,
)


@pytest.mark.asyncio
async def test_send_verification_api(
    client,
    auth_patient,
    monkeypatch,
):
    async def fake_send_email_verification_email(**kwargs):
        return None

    monkeypatch.setattr(
        "app.services.auth_service.send_email_verification_email",
        fake_send_email_verification_email,
    )

    response = await client.post(
        "/auth/send-verification",
        headers=auth_patient["headers"],
    )

    assert response.status_code == 200

    assert response.json() == {
        "message": "Verification email sent successfully."
    }


@pytest.mark.asyncio
async def test_send_verification_api_already_verified(
    client,
    auth_patient,
):
    auth_patient["user"].is_email_verified = True

    response = await client.post(
        "/auth/send-verification",
        headers=auth_patient["headers"],
    )

    assert response.status_code == 400

    assert response.json()["error"]["type"] == "BadRequestError"
    assert response.json()["error"]["message"] == (
        "Email is already verified."
    )


@pytest.mark.asyncio
async def test_verify_email_api_success(
    client,
    db,
    user,
):
    token = generate_secure_token()

    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            + timedelta(hours=24),
        )
    )

    await db.flush()

    response = await client.post(
        "/auth/verify-email",
        json={
            "token": token,
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "message": "Email verified successfully."
    }


@pytest.mark.asyncio
async def test_verify_email_api_invalid_token(
    client,
):
    response = await client.post(
        "/auth/verify-email",
        json={
            "token": "invalid-token",
        },
    )

    assert response.status_code == 400

    assert response.json()["error"]["type"] == "BadRequestError"
    assert response.json()["error"]["message"] == (
        "Invalid verification token."
    )


@pytest.mark.asyncio
async def test_verify_email_api_expired_token(
    client,
    db,
    user,
):
    token = generate_secure_token()

    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            - timedelta(minutes=1),
        )
    )

    await db.flush()

    response = await client.post(
        "/auth/verify-email",
        json={
            "token": token,
        },
    )

    assert response.status_code == 400

    assert response.json()["error"]["type"] == "BadRequestError"
    assert response.json()["error"]["message"] == (
        "Verification token has expired."
    )


@pytest.mark.asyncio
async def test_verify_email_api_used_token(
    client,
    db,
    user,
):
    token = generate_secure_token()

    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            + timedelta(hours=24),
            used=True,
        )
    )

    await db.flush()

    response = await client.post(
        "/auth/verify-email",
        json={
            "token": token,
        },
    )

    assert response.status_code == 400

    assert response.json()["error"]["type"] == "BadRequestError"
    assert response.json()["error"]["message"] == (
        "Verification token has already been used."
    )