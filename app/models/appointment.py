from sqlalchemy import (
    text,Integer, DateTime, Enum, ForeignKey, String, Text,event,func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

import enum

from app.db.base import Base
from datetime import datetime,timedelta
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from psycopg2.extras import DateTimeTZRange
from sqlalchemy.dialects.postgresql import Range



class AppointmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    SCHEDULED = "SCHEDULED"
    NO_SHOW = "NO_SHOW" 

class Appointment(Base):
    __tablename__ = "appointments"

    __table_args__ = (
        ExcludeConstraint(
            ("doctor_id", "="),
            ("time_range", "&&"),
            name="appointments_no_overlap",
            using="gist",
        ),
      
    )

   

    APPOINTMENT_DURATION = timedelta(minutes=30)

    id: Mapped[int] = mapped_column(primary_key=True)


    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    scheduled_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False,index=True,
    )

    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            name="appointmentstatus",
            create_type=False,
        ),
        default=AppointmentStatus.PENDING,
        nullable=False,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(String(500))

    # 🔹 AUDIT FIELDS
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    time_range: Mapped[object] = mapped_column(
        TSTZRANGE,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default="1",
    )

    __mapper_args__ = {
        "version_id_col": version
    }

   
    # ✅ relationships (explicit foreign_keys)
    doctor = relationship(
        "Doctor",
        back_populates="appointments",
        lazy="selectin",
    )

    patient = relationship(
        "User",
        foreign_keys=[patient_id],
        back_populates="patient_appointments",
        lazy="selectin",
    )

    cancelled_by_user = relationship(
        "User",
        foreign_keys=[cancelled_by],
        lazy="selectin",
    )


    
@event.listens_for(Appointment, "before_insert")
@event.listens_for(Appointment, "before_update")
def set_time_range(mapper, connection, target):
    if target.scheduled_at:
        start = target.scheduled_at
        end = start + Appointment.APPOINTMENT_DURATION
        #target.time_range = func.tstzrange(start, end, "[)")
        target.time_range = Range(start, end, bounds="[)")


from sqlalchemy import event
from datetime import datetime
from app.core.time import UTC


@event.listens_for(Appointment, "before_insert")
@event.listens_for(Appointment, "before_update")
def set_status_timestamps(mapper, connection, target):

    now = datetime.now(UTC)

    if target.status == AppointmentStatus.CONFIRMED and not target.confirmed_at:
        target.confirmed_at = now

    if target.status == AppointmentStatus.COMPLETED and not target.completed_at:
        target.completed_at = now

    if target.status == AppointmentStatus.CANCELLED and not target.cancelled_at:
        target.cancelled_at = now

