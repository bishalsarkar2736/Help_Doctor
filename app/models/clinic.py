from datetime import datetime

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    func,
    
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,relationship
)

from app.db.base import Base



class Clinic(Base):

    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
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