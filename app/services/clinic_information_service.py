"""What a clinic publishes about itself.

Backs the scheduling assistant's "what is your address?", "when do you close?"
and "are you open on Friday?", and stays a plain service so the admin screens
and any future public page read the same answers.

Everything here is information a clinic already advertises: name, address,
phone, hours. Nothing patient-specific passes through, which is what lets the
assistant answer it without a login.

WHAT IS NOT KNOWN IS SAID PLAINLY
---------------------------------
A clinic that has not recorded its hours produces "unknown", never a guess. An
assistant that invents nine-to-five sends someone to a locked door, and the
whole point of putting the backend in front of the model is that it does not
invent facts of this kind.
"""

from datetime import date, datetime, time

from app.core.time import utc_now
from app.core.tz import to_zoneinfo
from app.models.clinic import Clinic

# Monday=0, matching date.weekday() and DoctorAvailability.day_of_week, so the
# clinic's hours and its doctors' availability are never read against
# different calendars.
WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def clinic_timezone(clinic: Clinic):
    return to_zoneinfo(clinic.timezone)


def get_clinic_information(clinic: Clinic) -> dict:
    """The contact details a clinic publishes.

    Takes the already-resolved Clinic rather than an id: the caller has passed
    tenant resolution to get here, and re-reading by id would be a second place
    that could load a different clinic than the request was scoped to.
    """
    return {
        "clinic_id": clinic.id,
        "name": clinic.name,
        "address": clinic.address,
        "phone": clinic.phone,
        "email": clinic.email,
        "website": clinic.website,
        "timezone": clinic.timezone,
    }


def _ranges_for_weekday(clinic: Clinic, weekday: int) -> list[dict]:
    """Opening ranges for a weekday, as stored. Empty means closed."""
    hours = clinic.opening_hours or {}

    # Keys are strings: JSON objects have no integer keys, and a dict that has
    # been through a JSON round trip would otherwise miss on an int lookup.
    return hours.get(str(weekday)) or []


def get_clinic_opening_hours(clinic: Clinic) -> dict:
    """The whole week, one entry per day, named rather than numbered."""
    hours = clinic.opening_hours or {}

    return {
        "clinic_id": clinic.id,
        "timezone": clinic.timezone,
        # False when nothing has been recorded at all, so a caller can tell
        # "closed all week" apart from "never configured".
        "is_configured": bool(hours),
        "days": [
            {
                "weekday": weekday,
                "name": WEEKDAY_NAMES[weekday],
                "ranges": _ranges_for_weekday(clinic, weekday),
                "is_closed": not _ranges_for_weekday(clinic, weekday),
            }
            for weekday in range(7)
        ],
    }


def get_clinic_holiday_schedule(clinic: Clinic) -> list[dict]:
    """Recorded closures, earliest first."""
    holidays = clinic.holiday_schedule or []

    return sorted(holidays, key=lambda entry: entry.get("date", ""))


def holiday_on(clinic: Clinic, on: date) -> dict | None:
    """The holiday closing the clinic on `on`, if there is one."""
    wanted = on.isoformat()

    for entry in clinic.holiday_schedule or []:
        if entry.get("date") == wanted:
            return entry

    return None


def _parse(value: str) -> time | None:
    """"09:00" -> time(9, 0). Unparseable values are ignored, not raised on.

    Hours are validated on write; a value that survived that and still cannot
    be read means one bad range should not take down every answer about the
    clinic.
    """
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def is_open_at(clinic: Clinic, moment: datetime) -> dict:
    """Whether the clinic is open at `moment`, judged in its own timezone.

    The instant is converted into the clinic's local wall clock before anything
    is compared, because opening hours are written as local time and a server
    running in UTC would otherwise answer for the wrong hour — six hours out
    for the clinics this platform serves.
    """
    tz = clinic_timezone(clinic)
    local = moment.astimezone(tz)

    if not clinic.opening_hours:
        return {
            "is_open": None,
            "reason": "opening_hours_not_configured",
            "local_time": local.isoformat(),
        }

    holiday = holiday_on(clinic, local.date())

    if holiday is not None:
        return {
            "is_open": False,
            "reason": "holiday",
            "holiday": holiday,
            "local_time": local.isoformat(),
        }

    ranges = _ranges_for_weekday(clinic, local.weekday())

    if not ranges:
        return {
            "is_open": False,
            "reason": "closed_today",
            "local_time": local.isoformat(),
        }

    now = local.time()

    for entry in ranges:
        opens = _parse(entry.get("open", ""))
        closes = _parse(entry.get("close", ""))

        if opens is None or closes is None:
            continue

        if opens <= now < closes:
            return {
                "is_open": True,
                "reason": "within_opening_hours",
                "closes_at": entry.get("close"),
                "local_time": local.isoformat(),
            }

    return {
        "is_open": False,
        "reason": "outside_opening_hours",
        "ranges": ranges,
        "local_time": local.isoformat(),
    }


def is_open_now(clinic: Clinic) -> dict:
    """`is_open_at` for the current instant.

    Separate from is_open_at so that "now" is injectable: a test that had to
    wait for a Tuesday afternoon to check Tuesday afternoon would not be
    written at all.
    """
    return is_open_at(clinic, utc_now())
