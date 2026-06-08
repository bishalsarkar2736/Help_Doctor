from sqlalchemy import Integer, Time, Boolean, ForeignKey,Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DoctorAvailability(Base):
    __tablename__ = "doctor_availability"

    __table_args__ = (
        Index("idx_doctor_availability_doctor_id", "doctor_id"),
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

    doctor = relationship("Doctor", back_populates="availability")
