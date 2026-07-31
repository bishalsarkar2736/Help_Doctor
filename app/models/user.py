from sqlalchemy import String, Boolean,DateTime,Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.security.field_encryption import EncryptedSecret
from datetime import datetime
from app.core.time import UTC
from enum import Enum


# Role Enum

class UserRole(str,Enum):
    SUPER_ADMIN = 'super_admin'
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
        String(255), nullable=True
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

    # Soft delete — mirrors Clinic.deleted_at. Users are NEVER hard-deleted:
    # their appointments, prescriptions and payments carry medical/financial
    # retention obligations, and the FKs to this table are RESTRICT so the
    # database refuses a hard delete outright.
    #
    # is_active=False  -> temporarily suspended, can be re-enabled
    # deleted_at set   -> gone for good; cannot authenticate
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    clinic_id: Mapped[int | None] = mapped_column(
        ForeignKey("clinics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #audit fields
    created_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False
    )

    updated_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False
    )

    google_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
    )

    is_email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # --- MFA (TOTP) ---
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    # ENCRYPTED AT REST. A TOTP secret is a symmetric seed, not a password —
    # whoever holds it can mint valid codes forever, so a leaked dump or a
    # stolen backup would silently defeat every second factor in the system
    # with nothing in the audit trail to show for it.
    #
    # EncryptedSecret handles this in the mapper, so this attribute still reads
    # and writes as a plain string everywhere else. 255 rather than 64 because
    # a Fernet token of a 32-character seed is ~140 characters; the old width
    # would have truncated the ciphertext and destroyed the secret.
    mfa_secret: Mapped[str | None] = mapped_column(
        EncryptedSecret(255),
        nullable=True,
    )

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

    patient = relationship(
        "Patient",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    doctor = relationship(
        "Doctor",
        back_populates="user",
        foreign_keys="Doctor.user_id",
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

    clinic = relationship(
        "Clinic",
        back_populates="admins",
        lazy="selectin",
    )

    password_reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    email_verification_tokens = relationship(
        "EmailVerificationToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )


