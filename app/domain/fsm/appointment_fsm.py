# from app.models.appointment import AppointmentStatus
# from app.try_except.exceptions import BadRequestError

# class AppointmentFSM:

#     _transitions = {
#         AppointmentStatus.PENDING: {
#             AppointmentStatus.CONFIRMED,
#             AppointmentStatus.CANCELLED,
#         },
#         AppointmentStatus.CONFIRMED: {
#             AppointmentStatus.COMPLETED,
#             AppointmentStatus.CANCELLED,
#             AppointmentStatus.NO_SHOW,
#         },
#         AppointmentStatus.SCHEDULED: {
#             AppointmentStatus.CONFIRMED,
#             AppointmentStatus.CANCELLED,
#         },

#         # terminal states
#         AppointmentStatus.CANCELLED: set(),
#         AppointmentStatus.COMPLETED: set(),
#         AppointmentStatus.NO_SHOW: set(),
#     }

#     @classmethod
#     def can_transition(cls, current, target):
#         if isinstance(current, str):
#             current = AppointmentStatus(current.upper())

#         allowed = cls._transitions.get(current, set())

#         if target not in allowed:
#             raise BadRequestError(
#                 f"Invalid appointment transition: {current} → {target}"
#             )


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

        AppointmentStatus.SCHEDULED: {
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CANCELLED,
        },

        AppointmentStatus.CONFIRMED: {
            AppointmentStatus.IN_CONSULTATION,
            AppointmentStatus.COMPLETED,
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