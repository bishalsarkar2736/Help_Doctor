from datetime import datetime
from enum import Enum

from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    DateTime,
    text,
    Numeric,
    Enum as SQLEnum,
)
from decimal import Decimal
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.prescription import Prescription


class DoctorStatus(str, Enum):
    """Doctor lifecycle — the single source of truth for verification.

    Values equal names (matches the project's enum convention).
    """
    PENDING = "PENDING"      # profile created / applied, awaiting review
    APPROVED = "APPROVED"    # verified — visible in directory, can practice
    REJECTED = "REJECTED"    # application declined
    SUSPENDED = "SUSPENDED"  # previously approved, temporarily disabled


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )

    specialization: Mapped[str] = mapped_column(String(100), nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    bio: Mapped[str] = mapped_column(String(500))

    status: Mapped[DoctorStatus] = mapped_column(
        SQLEnum(DoctorStatus, name="doctor_status", create_type=False),
        default=DoctorStatus.PENDING,
        server_default="PENDING",
        nullable=False,
        index=True,
    )

    # --- Approval / rejection audit ---
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rejected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    qualification: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    medical_registration_number: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )

    signature_file_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    signature_uploaded_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    clinic_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="RESTRICT",   # or remove ondelete
        ),
        nullable=True,
        index=True,
    )

    consultation_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00"),
    )

    clinic = relationship(
        "Clinic",
        back_populates="doctors",
        lazy="selectin",
    )
    

    user = relationship(
        "User",
        back_populates="doctor",
        foreign_keys="Doctor.user_id",
        lazy="selectin",
    )
    
    documents = relationship(
        "DoctorDocument",
        back_populates="doctor",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    availability = relationship(
        "DoctorAvailability",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )

    appointments = relationship(
        "Appointment",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )

    slots = relationship(
        "DoctorSlot",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )


    doctor_prescriptions: Mapped[list["Prescription"]] = relationship(
        "Prescription",
        back_populates="doctor",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    



