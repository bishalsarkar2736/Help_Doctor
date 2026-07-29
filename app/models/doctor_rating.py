"""Patient rating of a doctor, tied to one completed appointment.

Two deliberate constraints shape this table:

* ``appointment_id`` is UNIQUE — a rating is always anchored to a real visit,
  so a patient cannot rate the same doctor repeatedly and drive the average.
* ``comment`` is private to the clinic administrator. Stars aggregate into a
  public average; the free text does not, because it is written about a named
  clinician and patients routinely disclose their own condition in it.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAX_COMMENT_LENGTH = 2000


class DoctorRating(Base):

    __tablename__ = "doctor_ratings"

    __table_args__ = (
        UniqueConstraint(
            "appointment_id",
            name="uq_doctor_ratings_appointment_id",
        ),
        CheckConstraint(
            "stars >= 1 AND stars <= 5",
            name="ck_doctor_ratings_stars_range",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Mirrors appointments.patient_id, which references users.id (not
    # patients.id) — keeping them the same makes the join trivial.
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Denormalised from the appointment so admin moderation queries stay
    # single-table, and so a doctor moving clinics cannot retroactively drag
    # old ratings into the new clinic's dashboard.
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    stars: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
