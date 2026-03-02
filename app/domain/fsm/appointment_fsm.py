from app.models.appointment import AppointmentStatus
from app.try_except.exceptions import ConflictError,BadRequestError

class AppointmentFSM:

    _transitions = {
        AppointmentStatus.PENDING: {
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CANCELLED,
        },
        AppointmentStatus.CONFIRMED: {
            AppointmentStatus.COMPLETED,
            AppointmentStatus.CANCELLED,
            AppointmentStatus.NO_SHOW,
        },

        # terminal states
        AppointmentStatus.CANCELLED: set(),
        AppointmentStatus.COMPLETED: set(),
        AppointmentStatus.NO_SHOW: set(),
    }

    @classmethod
    def can_transition(cls, current, target):
        if isinstance(current, str):
            current = AppointmentStatus(current.upper())

        allowed = cls._transitions.get(current, set())

        if target not in allowed:
            raise BadRequestError(
                f"Invalid appointment transition: {current} → {target}"
            )
