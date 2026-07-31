"""Role-based MFA requirement and its staged rollout.

The rollout order is super_admin -> admin -> doctor -> receptionist, driven by
MFA_REQUIRED_ROLES so a clinic can enrol one group at a time.

The most important test here is the lockout one. The intuitive enforcement —
refuse login until MFA is on — is unrecoverable: enrolling needs an
authenticated session, so a blocked account can never obtain the token it needs
to enrol. For a super_admin that means the platform plane is locked with no way
back, and no amount of retrying fixes it.
"""

import pytest

from app.config import Settings, get_settings
from app.models.user import UserRole
from app.security.mfa_policy import (
    mfa_enrollment_pending,
    mfa_required_for,
)


@pytest.fixture
def require_mfa_for(monkeypatch):
    """Point the whole app at a Settings with a chosen MFA_REQUIRED_ROLES."""

    def _apply(roles: str):
        base = get_settings()
        overridden = base.model_copy(update={"MFA_REQUIRED_ROLES": roles})

        for module in (
            "app.config",
            "app.security.mfa_policy",
        ):
            monkeypatch.setattr(
                module + ".get_settings", lambda: overridden, raising=False
            )
        return overridden

    return _apply


# ---------------------------------------------------------------------------
# Rollout configuration
# ---------------------------------------------------------------------------


def test_default_requires_super_admin_first():
    """The platform plane is the smallest, highest-blast-radius group."""
    assert "super_admin" in get_settings().mfa_required_roles


@pytest.mark.parametrize(
    "configured,role,expected",
    [
        ("super_admin", UserRole.SUPER_ADMIN, True),
        ("super_admin", UserRole.ADMIN, False),
        ("super_admin,admin", UserRole.ADMIN, True),
        ("super_admin,admin,doctor", UserRole.DOCTOR, True),
        ("super_admin,admin,doctor", UserRole.RECEPTIONIST, False),
        ("super_admin,admin,doctor,receptionist", UserRole.RECEPTIONIST, True),
        ("", UserRole.SUPER_ADMIN, False),
    ],
)
def test_rollout_widens_one_group_at_a_time(
    require_mfa_for, configured, role, expected
):
    require_mfa_for(configured)
    assert mfa_required_for(role) is expected


def test_role_matching_is_case_insensitive(require_mfa_for):
    """A config of SUPER_ADMIN must not silently disable the requirement.

    UserRole values are lowercase, so a case-sensitive compare would match
    nothing and turn the control off with no error anywhere.
    """
    require_mfa_for("SUPER_ADMIN, Admin")
    assert mfa_required_for(UserRole.SUPER_ADMIN) is True
    assert mfa_required_for(UserRole.ADMIN) is True


def test_whitespace_and_empty_entries_are_tolerated(require_mfa_for):
    require_mfa_for(" super_admin , , admin ")
    assert mfa_required_for(UserRole.ADMIN) is True


def test_settings_parses_roles_into_a_set():
    s = Settings(MFA_REQUIRED_ROLES="super_admin,admin")
    assert s.mfa_required_roles == {"super_admin", "admin"}


# ---------------------------------------------------------------------------
# Enrolment state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_when_role_requires_and_user_has_not_enrolled(
    require_mfa_for, auth_admin
):
    require_mfa_for("admin")
    assert mfa_enrollment_pending(auth_admin["user"]) is True


@pytest.mark.asyncio
async def test_not_pending_once_enrolled(require_mfa_for, db, auth_admin):
    require_mfa_for("admin")
    auth_admin["user"].mfa_enabled = True
    await db.flush()
    assert mfa_enrollment_pending(auth_admin["user"]) is False


@pytest.mark.asyncio
async def test_not_pending_when_the_role_is_not_in_the_rollout(
    require_mfa_for, auth_admin
):
    require_mfa_for("super_admin")
    assert mfa_enrollment_pending(auth_admin["user"]) is False


# ---------------------------------------------------------------------------
# The lockout trap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_still_works_while_enrolment_is_outstanding(
    client, require_mfa_for, db
):
    """Refusing login here would be unrecoverable — see the module docstring."""
    from app.models.user import User
    from app.security.jwt import hash_password

    require_mfa_for("admin")

    user = User(
        email="mfa.pending@example.com",
        hashed_password=hash_password("Sup3rSecret!pw"),
        role=UserRole.ADMIN,
        is_active=True,
        is_email_verified=True,
        mfa_enabled=False,
    )
    db.add(user)
    await db.commit()

    res = await client.post(
        "/auth/login",
        data={"username": user.email, "password": "Sup3rSecret!pw"},
    )
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["access_token"], "no token issued — the account cannot enrol"
    assert body["mfa_enrollment_required"] is True


@pytest.mark.asyncio
async def test_the_enrolment_route_is_reachable_without_mfa(
    client, require_mfa_for, auth_admin
):
    """The way out must never be behind the gate."""
    require_mfa_for("admin")

    res = await client.post("/auth/mfa/setup", headers=auth_admin["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["secret"]


# ---------------------------------------------------------------------------
# Enforcement on a privileged endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phi_access_log_refused_while_enrolment_outstanding(
    client, require_mfa_for, auth_admin, default_clinic
):
    require_mfa_for("admin")

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403, res.text
    assert "MFA_ENROLLMENT_REQUIRED" in res.text


@pytest.mark.asyncio
async def test_phi_access_log_allowed_once_enrolled(
    client, require_mfa_for, db, auth_admin, default_clinic
):
    """Paired allow-case: the refusal above is the policy, not a broken route."""
    require_mfa_for("admin")

    auth_admin["user"].mfa_enabled = True
    await db.commit()

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_phi_access_log_unaffected_when_role_not_in_rollout(
    client, require_mfa_for, auth_admin, default_clinic
):
    """Default config must not change existing behaviour for admins."""
    require_mfa_for("super_admin")

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text
