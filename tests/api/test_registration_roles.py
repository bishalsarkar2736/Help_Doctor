"""Public signup must not be able to mint privileged accounts.

Regression guard: /auth/register previously took `role` straight from the
request body, so anyone could POST role="super_admin" and create a platform
account.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.limiter import limiter
from app.models.user import User, UserRole


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


def _payload(role: str | None = None) -> dict:
    body = {
        "email": f"reg-{uuid.uuid4().hex[:10]}@test.com",
        "password": "Test12345",
        "full_name": "Reg Test",
    }
    if role is not None:
        body["role"] = role
    return body


@pytest.mark.parametrize("role", ["admin", "super_admin", "receptionist", "doctor"])
@pytest.mark.asyncio
async def test_privileged_roles_cannot_self_register(client, db, role):
    body = _payload(role)
    res = await client.post("/auth/register", json=body)

    assert res.status_code in (400, 403, 422), (
        f"role={role} must be rejected, got {res.status_code}"
    )

    # And nothing was persisted.
    user = await db.scalar(select(User).where(User.email == body["email"]))
    assert user is None


@pytest.mark.asyncio
async def test_only_patients_can_self_register(client, db):
    """Patients are the only public users; doctors now join by invitation."""
    body = _payload("patient")
    res = await client.post("/auth/register", json=body)
    assert res.status_code == 201, res.text

    user = await db.scalar(select(User).where(User.email == body["email"]))
    assert user is not None
    assert user.role is UserRole.PATIENT


@pytest.mark.asyncio
async def test_role_defaults_to_patient_when_omitted(client, db):
    body = _payload(None)
    res = await client.post("/auth/register", json=body)
    assert res.status_code == 201, res.text

    user = await db.scalar(select(User).where(User.email == body["email"]))
    # Must NOT fall back to the old RECEPTIONIST default.
    assert user.role is UserRole.PATIENT
