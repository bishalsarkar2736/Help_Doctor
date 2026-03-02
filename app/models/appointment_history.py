from datetime import datetime
from sqlalchemy import ForeignKey, DateTime, Enum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.appointment import AppointmentStatus
from app.core.time import UTC


class AppointmentStatusHistory(Base):
    __tablename__ = "appointment_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
    )

    old_status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus),
        nullable=False,
    )

    new_status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus),
        nullable=False,
    )

    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,  # NULL = system action
    )

    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    appointment = relationship("Appointment")
