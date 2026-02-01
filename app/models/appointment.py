from sqlalchemy import (
    Integer, DateTime, Enum, ForeignKey, String, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import enum

from app.db.base import Base


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    scheduled_at: Mapped[DateTime] = mapped_column(
        DateTime, nullable=False
    )

    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus),
        default=AppointmentStatus.PENDING,
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(String(500))

    # 🔹 AUDIT FIELDS
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[DateTime | None] = mapped_column(DateTime)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

   
    # ✅ relationships (explicit foreign_keys)
    doctor = relationship(
        "Doctor",
        back_populates="appointments",
        lazy="joined",
    )

    patient = relationship(
        "User",
        foreign_keys=[patient_id],
        back_populates="patient_appointments",
        lazy="joined",
    )

    cancelled_by_user = relationship(
        "User",
        foreign_keys=[cancelled_by],
        lazy="joined",
    )
