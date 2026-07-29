from app.try_except.exceptions import ForbiddenError
from app.models.user import UserRole
from app.models.doctor import DoctorStatus


class DoctorPolicy:

    @staticmethod
    def can_create_profile(user):
        if user.role == UserRole.DOCTOR:
            return True

        raise ForbiddenError("Only doctors can create doctor profile")

    @staticmethod
    def can_verify(user):
        if user.role == UserRole.ADMIN:
            return True

        raise ForbiddenError("Only admin can verify doctor")

    @staticmethod
    def can_be_viewed_by(user, doctor):
        # Admin can view all
        if user.role == UserRole.ADMIN:
            return True

        # Doctor can view own profile
        if user.role == UserRole.DOCTOR and user.id == doctor.user_id:
            return True

        # Patient can view only verified doctors
        if user.role == UserRole.PATIENT and doctor.status == DoctorStatus.APPROVED:
            return True

        raise ForbiddenError("You are not allowed to view this doctor")
