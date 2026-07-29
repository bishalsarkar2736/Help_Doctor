import logging
from types import MappingProxyType
from app.models.appointment import AppointmentStatus
from app.try_except.exceptions import BadRequestError

logger = logging.getLogger(__name__)


class AppointmentFSM:

    _transitions = MappingProxyType({
        AppointmentStatus.PENDING: {
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CANCELLED,
        },

        AppointmentStatus.CONFIRMED: {
            AppointmentStatus.IN_CONSULTATION,

            AppointmentStatus.CHECKED_IN,

            AppointmentStatus.COMPLETED,
            AppointmentStatus.CANCELLED,
            AppointmentStatus.NO_SHOW,

            # Reschedule re-opens confirmation: a rescheduled CONFIRMED
            # appointment returns to PENDING for the doctor to re-confirm.
            AppointmentStatus.PENDING,
        },

        AppointmentStatus.CHECKED_IN: {
            # WAITING is optional — a checked-in patient can be taken
            # straight in when the doctor is free.
            AppointmentStatus.WAITING,
            AppointmentStatus.IN_CONSULTATION,
            AppointmentStatus.CANCELLED,
        },
        
        AppointmentStatus.WAITING: {
            AppointmentStatus.IN_CONSULTATION,
            AppointmentStatus.CANCELLED,
            AppointmentStatus.NO_SHOW,
        },

        AppointmentStatus.IN_CONSULTATION: {
            AppointmentStatus.COMPLETED,
            AppointmentStatus.CANCELLED,
        },

        AppointmentStatus.CANCELLED: set(),
        AppointmentStatus.COMPLETED: set(),
        AppointmentStatus.NO_SHOW: set(),
    })

    @classmethod
    def can_transition(cls, current, target):

        if isinstance(current, str):
            try:
                current = AppointmentStatus(current.upper())
            except ValueError:
                raise BadRequestError(f"Invalid status in DB: {current}")

        allowed = cls._transitions.get(current, set())

        if target not in allowed:

            logger.warning(
                "Invalid appointment transition",
                extra={"current": current, "target": target},
            )

            raise BadRequestError(
                f"Invalid appointment transition: {current} → {target}"
            )