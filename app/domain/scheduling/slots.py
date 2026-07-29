from datetime import datetime
from app.core.time import UTC
from app.try_except.exceptions import BadRequestError
from app.core.constants import APPOINTMENT_DURATION_MINUTES

def validate_exact_slot(dt: datetime) -> None:
    dt = dt.astimezone(UTC)

    if dt.second != 0 or dt.microsecond != 0:
        raise BadRequestError("Appointments must be booked on exact time slots")

    if dt.minute % APPOINTMENT_DURATION_MINUTES != 0:
        raise BadRequestError(
            f"Appointments must be booked in {APPOINTMENT_DURATION_MINUTES}-minute slots"
        )