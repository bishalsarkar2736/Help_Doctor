"""Whether a doctor's time is taken, derived from appointments.

doctor_slots used to carry an is_booked column. Nothing ever set it — no code,
no trigger, no migration — so every slot reported itself free forever. The
public slot list offered booked times, `only_available=true` filtered nothing,
the assistant recommended occupied slots, and doctor utilisation was
permanently zero. Patients picked a slot the screen called free and were then
refused by the exclusion constraint.

A column would have been the wrong fix even maintained correctly: it is a second
copy of a fact the appointments table already holds, and the two drift the first
time a booking path forgets to update it. The one thing that cannot drift from
the appointments table is the appointments table.

So there is no stored flag. Occupancy is a predicate over appointments, defined
here once and used by the slot list, the earliest-slot recommendation and the
utilisation figures, so those three cannot disagree with each other or with what
booking will actually allow.

TWO QUESTIONS, TWO ANSWERS
"Can this slot be booked?" and "was this slot used?" are different, and using
one set for both is what made utilisation meaningless.

BLOCKING_STATUSES mirrors the exclusion constraint on appointments:

    EXCLUDE USING gist (doctor_id WITH =, time_range WITH &&)
        WHERE status IN ('PENDING','CONFIRMED')

Deliberately the SAME set, not a wider or safer one. Availability has to agree
with what the database will actually permit: a wider set would mark slots
unavailable that booking would happily accept, hiding bookable time, and a
narrower one would offer slots that then fail. Mirroring is the only
self-consistent choice, and it is why this constant names the constraint.

(An appointment that has reached CHECKED_IN, WAITING or IN_CONSULTATION does not
block under that constraint. That is the constraint's existing scope, not a
decision taken here, and it is unobservable in practice because those statuses
are only reached once the slot is in the past and past slots cannot be booked.)

UTILISED_STATUSES is everything except CANCELLED. A completed consultation used
the doctor's time; so did a no-show, which is time that was reserved and
wasted. Only a cancellation gives it back. Measuring utilisation with
BLOCKING_STATUSES instead would count no past appointment at all, since they
all end up COMPLETED or NO_SHOW — which is exactly why the old figure read
zero.
"""

from sqlalchemy import and_, exists, select
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlalchemy.sql import func

from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor_slot import DoctorSlot

# The exclusion constraint's WHERE clause. Changing this without changing the
# constraint puts the slot list and the database back into disagreement.
BLOCKING_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
)

# Time the doctor spent, or held and lost. Everything a cancellation is not.
UTILISED_STATUSES = tuple(
    status for status in AppointmentStatus if status != AppointmentStatus.CANCELLED
)


def _overlaps_slot(statuses):
    """An appointment in `statuses` covering this slot's interval.

    Overlap rather than `scheduled_at == start_time`: it is the same test the
    exclusion constraint applies, so the answer cannot depend on slot and
    appointment durations happening to be configured identically. The GiST
    index backing that constraint serves this too.
    """
    slot_range = func.tstzrange(
        DoctorSlot.start_time,
        DoctorSlot.end_time,
        "[)",
        type_=TSTZRANGE,
    )

    return exists(
        select(Appointment.id).where(
            and_(
                Appointment.doctor_id == DoctorSlot.doctor_id,
                Appointment.status.in_(statuses),
                Appointment.time_range.op("&&")(slot_range),
            )
        )
    )


def slot_is_blocked():
    """SQL predicate: this slot cannot be booked.

    Correlates on DoctorSlot, so it belongs in a query that already selects
    from doctor_slots — as a select column to render `is_booked`, or in a WHERE
    clause to filter.
    """
    return _overlaps_slot(BLOCKING_STATUSES)


def slot_is_utilised():
    """SQL predicate: this slot's time was taken, for utilisation figures."""
    return _overlaps_slot(UTILISED_STATUSES)
