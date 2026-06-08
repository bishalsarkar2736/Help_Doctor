from sqlalchemy import String, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.prescription import Prescription


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    specialization: Mapped[str] = mapped_column(String(100), nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    bio: Mapped[str] = mapped_column(String(500))

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[DateTime] = mapped_column(
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
    

    user = relationship(
        "User", 
        back_populates="doctor",
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

    



