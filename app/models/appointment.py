from sqlalchemy import (
    text,Integer, 
    DateTime,
    Boolean, 
    Enum, 
    ForeignKey, 
    String, 
    Text,
    event,
    func,
    Numeric,
)
from decimal import Decimal
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.time import UTC
import enum
from app.core.constants import APPOINTMENT_DURATION
from app.db.base import Base
from datetime import datetime
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlalchemy.dialects.postgresql import ExcludeConstraint




class AppointmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"

    CHECKED_IN = "CHECKED_IN"
    WAITING = "WAITING"

    IN_CONSULTATION = "IN_CONSULTATION"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
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

   

    APPOINTMENT_DURATION = APPOINTMENT_DURATION

    id: Mapped[int] = mapped_column(primary_key=True)


    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
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

    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    waiting_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    consultation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reminder_sent: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
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

    clinic_id: Mapped[int] = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="RESTRICT",   # or remove ondelete
        ),
        nullable=False,
        index=True,
    )

    consultation_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00"),
    )

    queue_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    clinic = relationship(
        "Clinic",
        back_populates="appointments",
        lazy="selectin",
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

    prescription = relationship(
        "Prescription",
        back_populates="appointment",
        uselist=False,
        lazy="selectin",
    )



@event.listens_for(Appointment, "before_insert")
#@event.listens_for(Appointment, "before_update")
def set_status_timestamps(mapper, connection, target):

    now = datetime.now(UTC)

    if target.status == AppointmentStatus.CONFIRMED and not target.confirmed_at:
        target.confirmed_at = now

    if target.status == AppointmentStatus.COMPLETED and not target.completed_at:
        target.completed_at = now

    if target.status == AppointmentStatus.CANCELLED and not target.cancelled_at:
        target.cancelled_at = now

