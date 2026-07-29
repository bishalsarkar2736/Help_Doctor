"""Clinic timezone resolution.

Doctor availability is entered in the clinic's local wall-clock time; slot
generation and booking validation convert to/from UTC through the clinic's
IANA timezone. Unknown/blank names fall back to UTC so a bad value can never
crash scheduling.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.time import UTC


def to_zoneinfo(name: str | None):
    if not name or name == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return UTC
