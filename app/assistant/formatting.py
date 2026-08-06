"""Turning stored instants into what a clinic would say out loud.

Slots are stored in UTC. A patient asked about "tomorrow afternoon" and a
clinic answering "2:00 PM" are both speaking in the clinic's local time, and
the conversion between them is arithmetic — which is exactly what a language
model should never be asked to do.

So every time a tool returns is converted HERE and handed over already
formatted. The model is given "Tuesday 10 March, 2:00 PM" and repeats it. If it
were given "2026-03-10T08:00:00+00:00" and the clinic's timezone, it would have
to compute the answer, and a model that computes is a model that can be wrong
while sounding certain.

The machine-readable UTC value is returned alongside, because the frontend's
Book Appointment button needs to identify the slot exactly and a display string
is not an identifier.
"""

from datetime import datetime

from app.core.time import UTC

# 12-hour with an am/pm marker: how a clinic in this region writes a time, and
# how a patient reads one back.
TIME_FORMAT = "%-I:%M %p"
DATE_FORMAT = "%A %-d %B"


def to_local(moment: datetime, tz) -> datetime:
    """A stored instant in the clinic's own wall clock."""
    if moment.tzinfo is None:
        # Defensive: every column this reads is timezone=True, but a naive
        # value would otherwise be silently treated as local and shift the
        # answer by the clinic's whole offset.
        moment = moment.replace(tzinfo=UTC)

    return moment.astimezone(tz)


def local_time(moment: datetime, tz) -> str:
    """"2:00 PM"."""
    return to_local(moment, tz).strftime(TIME_FORMAT)


def local_date(moment: datetime, tz) -> str:
    """"Tuesday 10 March"."""
    return to_local(moment, tz).strftime(DATE_FORMAT)


def describe_slot(start: datetime, end: datetime, tz) -> dict:
    """One slot, in every form a caller downstream needs.

    `date` and `time` are for the model to repeat. `starts_at` is the exact
    instant, kept so the booking button refers to a slot rather than to a
    sentence about one.
    """
    return {
        "date": local_date(start, tz),
        "time": local_time(start, tz),
        "ends": local_time(end, tz),
        "starts_at": start.astimezone(UTC).isoformat(),
        "local_date": to_local(start, tz).date().isoformat(),
    }
