from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DoctorSlot(Base):
    __tablename__ = "doctor_slots"

    __table_args__ = (
        Index("idx_doctor_slot_doctor_time", "doctor_id", "start_time"),
        Index("uq_doctor_slot_unique", "doctor_id", "start_time", unique=True)
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
    )

    # timezone=True is load-bearing. slot_generation writes UTC-aware values
    # (.astimezone(UTC)) and get_doctor_slots filters with UTC-aware bounds, but
    # a naive column silently dropped the offset on write and then asyncpg
    # refused the aware query argument outright:
    #   DataError: can't subtract offset-naive and offset-aware datetimes
    # which surfaced as a 500 on the patient booking screen — and, because a 500
    # carries no CORS headers, as an opaque "blocked by CORS" error in the
    # browser rather than anything pointing at the real cause.
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # NO is_booked COLUMN, DELIBERATELY.
    #
    # There was one. Nothing ever wrote True to it -- no code, no trigger, no
    # migration -- so every slot reported itself free forever: the public list
    # offered booked times, only_available filtered nothing, the assistant
    # recommended occupied slots, and utilisation was permanently zero.
    #
    # It is not re-added maintained, because a stored flag is a second copy of
    # what the appointments table already knows, and the two drift the first
    # time a booking path forgets to update one. Occupancy is derived instead --
    # see app/domain/scheduling/occupancy.py -- from the same predicate the
    # exclusion constraint uses, so a slot cannot claim to be free while the
    # database refuses to book it.
    #
    # The API still returns an `is_booked` field. It is computed per request.


    doctor = relationship(
    "Doctor",
    back_populates="slots",
    )