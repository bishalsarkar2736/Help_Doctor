from app.try_except.exceptions import ForbiddenError
from app.models.user import UserRole


class DoctorPolicy:
    """Role checks for doctor profiles.

    `can_verify` and `can_be_viewed_by` were removed here. Both answered
    "is this user an ADMIN?" and stopped, with no notion of which clinic the
    doctor belonged to, so either would have approved or exposed another
    tenant's doctor had anything called them. `can_be_viewed_by` had no
    callers at all; `can_verify` was reached only from verify_doctor, which
    was itself unreachable and is deleted with it.

    Doctor approval lives in admin_doctor_service.approve_doctor, which
    resolves the admin's clinic before assigning the doctor to it, and is the
    function actually wired to POST /admin/doctors/{id}/approve.
    """

    @staticmethod
    def can_create_profile(user):
        if user.role == UserRole.DOCTOR:
            return True

        raise ForbiddenError("Only doctors can create doctor profile")
