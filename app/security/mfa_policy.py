"""Who must use a second factor, and what happens until they do.

The rollout is deliberately staged (see MFA_REQUIRED_ROLES in config.py):

    super_admin -> admin -> doctor -> receptionist

Each stage is a config change, not a code change, so a clinic can enrol one
group at a time instead of locking out its whole staff on a single deploy.

THE LOCKOUT TRAP
----------------
The obvious enforcement — refuse to log in until MFA is enabled — is wrong and
unrecoverable. Enrolling requires calling /auth/mfa/setup with a valid access
token, so an account blocked at login can never obtain the session it needs to
enrol. For a super_admin, that is the platform plane locked with no way back.

So enforcement is split:

  * login still succeeds, and the response carries mfa_enrollment_required so
    the client can route straight to enrolment;
  * privileged endpoints depend on require_mfa_enrolled, which refuses until
    enrolment is finished.

The account can always reach /auth/mfa/setup and /auth/mfa/enable, because
those are never guarded by this dependency.
"""

from fastapi import Depends

from app.config import get_settings
from app.models.user import User
from app.security.jwt import get_current_user
from app.try_except.exceptions import ForbiddenError


def mfa_required_for(role: object) -> bool:
    """Does this role have to enrol?"""
    value = getattr(role, "value", role)
    return str(value).lower() in get_settings().mfa_required_roles


def mfa_enrollment_pending(user: User) -> bool:
    """Role requires a second factor, and the user has not set one up."""
    return mfa_required_for(user.role) and not user.mfa_enabled


async def require_mfa_enrolled(
    current_user: User = Depends(get_current_user),
) -> User:
    """Guard privileged operations behind a completed MFA enrolment.

    Deliberately NOT applied to the MFA setup/enable routes themselves — that
    would be the lockout described above.
    """
    if mfa_enrollment_pending(current_user):
        raise ForbiddenError(
            "MFA_ENROLLMENT_REQUIRED: this action requires two-factor "
            "authentication. Enrol at /auth/mfa/setup, then retry."
        )

    return current_user
