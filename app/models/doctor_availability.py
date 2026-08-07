from sqlalchemy import Boolean, Computed, ForeignKey, Index, Integer, Time, text
from sqlalchemy.dialects.postgresql import TSRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DoctorAvailability(Base):
    __tablename__ = "doctor_availability"

    __table_args__ = (
        Index("idx_doctor_availability_doctor_id", "doctor_id"),
        # The lookup the slot generator runs. Created by raw SQL in a
        # migration and never declared, so autogenerate wanted to drop it.
        Index(
            "idx_doctor_availability_lookup",
            "doctor_id",
            "day_of_week",
            "is_available",
            "start_time",
            "end_time",
        ),
        # A doctor cannot be available twice over the same interval. Enforced
        # by the database rather than by application code, which is why the
        # column below has to exist even though no Python reads it.
        ExcludeConstraint(
            ("doctor_id", "="),
            ("time_range", "&&"),
            name="doctor_availability_no_overlap",
            using="gist",
            where=text("is_available = true"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
    )

    day_of_week: Mapped[int] = mapped_column(Integer)  # 0=Mon … 6=Sun
    start_time: Mapped[str] = mapped_column(Time)
    end_time: Mapped[str] = mapped_column(Time)

    is_available: Mapped[bool] = mapped_column(Boolean, default=True)

    # GENERATED ALWAYS — Postgres computes this from the three columns above,
    # projecting the weekday and the two times onto a fixed reference date so
    # that two availability windows can be compared as ranges.
    #
    # Declared so autogenerate leaves it alone. Nothing in Python reads or
    # writes it, which is exactly why it was missing from this model and why
    # dropping it looked harmless: the overlap constraint above is built on it,
    # so op.drop_column would have taken the guarantee with it.
    #
    # Computed() rather than a plain column: the first attempt declared it
    # writable and every availability insert failed with GeneratedAlwaysError,
    # because SQLAlchemy included it in the INSERT.
    time_range: Mapped[object | None] = mapped_column(
        TSRANGE,
        Computed(
            "tsrange("
            "(('2000-01-01'::date + day_of_week) + start_time), "
            "(('2000-01-01'::date + day_of_week) + end_time), "
            "'[)'::text)",
            persisted=True,
        ),
        nullable=True,
    )

    doctor = relationship("Doctor", back_populates="availability")
