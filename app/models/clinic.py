from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    func,
    Enum as SQLEnum,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,relationship
)

from app.db.base import Base


class ClinicStatus(str, Enum):
    """Clinic lifecycle (platform-plane, super-admin controlled).

    Values equal names (project enum convention).
    """
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"   # temporarily disabled; users blocked from login
    DELETED = "DELETED"       # soft-deleted / archived (never hard-deleted)


class Clinic(Base):

    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    status: Mapped[ClinicStatus] = mapped_column(
        SQLEnum(ClinicStatus, name="clinic_status", create_type=False),
        default=ClinicStatus.ACTIVE,
        server_default="ACTIVE",
        nullable=False,
        index=True,
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        index=True,
        nullable=False,
    )

    logo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    phone: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    website: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    primary_color: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # IANA timezone name (e.g. "Asia/Dhaka"). Doctor availability is entered in
    # this local time; slots are generated / validated against it.
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="UTC",
        default="UTC",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    doctors = relationship(
        "Doctor",
        back_populates="clinic",
        lazy="selectin",
    )

    appointments = relationship(
        "Appointment",
        back_populates="clinic",
        lazy="selectin",
    )

    prescriptions = relationship(
        "Prescription",
        back_populates="clinic",
        lazy="selectin",
    )

    payments = relationship(
        "Payment",
        back_populates="clinic",
        lazy="selectin",
    )

    admins = relationship(
        "User",
        back_populates="clinic",
        lazy="selectin",
    )