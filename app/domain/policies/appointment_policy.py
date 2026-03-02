from app.try_except.exceptions import ForbiddenError


class AppointmentPolicy:

    @staticmethod
    def can_be_cancelled_by(user, appointment):
        if user.role == "admin":
            return True

        if user.role == "patient" and user.id == appointment.patient_id:
            return True

        if user.role == "doctor" and user.id == appointment.doctor_user_id:
            return True

        raise ForbiddenError("You cannot cancel this appointment")

    @staticmethod
    def can_be_updated_by(user, appointment):
        if user.role == "doctor" and user.id == appointment.doctor_user_id:
            return True

        raise ForbiddenError("Only assigned doctor can update appointment")
