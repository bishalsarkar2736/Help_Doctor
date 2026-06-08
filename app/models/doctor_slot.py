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

    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    is_booked: Mapped[bool] = mapped_column(Boolean, default=False)


    doctor = relationship(
    "Doctor",
    back_populates="slots",
    )