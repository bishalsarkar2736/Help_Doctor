from datetime import datetime
from sqlalchemy import ForeignKey, DateTime, Boolean, Index
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

    is_booked: Mapped[bool] = mapped_column(Boolean, default=False)


    doctor = relationship(
    "Doctor",
    back_populates="slots",
    )