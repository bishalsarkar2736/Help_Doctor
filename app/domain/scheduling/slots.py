from datetime import datetime
from app.core.time import UTC
from app.try_except.exceptions import BadRequestError


def validate_exact_slot(dt: datetime) -> None:
    dt = dt.astimezone(UTC)

    if dt.second != 0 or dt.microsecond != 0:
        raise BadRequestError("Appointments must be booked on exact time slots")

    if dt.minute not in (0, 30):
        raise BadRequestError("Appointments must be booked in 30-minute slots")