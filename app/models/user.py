from sqlalchemy import String, Boolean,DateTime,Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from datetime import datetime
from app.core.time import UTC
from enum import Enum


# Role Enum

class UserRole(str,Enum):
    ADMIN = 'admin'
    DOCTOR = 'doctor'
    RECEPTIONIST = 'receptionist'
    PATIENT = "patient"

class AuthProvider(str, Enum):
    LOCAL = "LOCAL"
    GOOGLE = "GOOGLE"


#User Model

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    email:Mapped[str] = mapped_column(
        String(255), unique=True, index=True,nullable=False
    )

    hashed_password : Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    full_name : Mapped[str | None] = mapped_column(String(255))

    role : Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, name = 'user_roles',create_type=False),
        default=UserRole.RECEPTIONIST,
        nullable=False
    )

    is_active : Mapped[bool] = mapped_column(
        Boolean, default=True,nullable=False
    )

    #audit fields
    created_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default = datetime.now(UTC),
        nullable=False
    )

    updated_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.now(UTC),
        onupdate=datetime.now(UTC),
        nullable=False
    )

    google_id : Mapped[str | None]
  
    auth_provider : Mapped[AuthProvider] = mapped_column(
        SQLEnum(AuthProvider,name="auth_provider",create_type=False),
        default=AuthProvider.LOCAL,
        nullable=False
    )

    # relationship (add here) one-to-one

    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    patients = relationship(
        "Patient",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    doctor = relationship(
        "Doctor",
        back_populates="user",
        uselist=False,
    )

    patient_appointments = relationship(
        "Appointment",
        foreign_keys="Appointment.patient_id",
        back_populates="patient",
    )

    patient_prescriptions = relationship(
        "Prescription",
        foreign_keys="[Prescription.patient_id]",
        back_populates="patient",
        lazy="selectin",
    )

    notification_preferences = relationship(
        "NotificationPreference",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )




