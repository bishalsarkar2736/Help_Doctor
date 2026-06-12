from sqlalchemy import (
    Integer,
    String,
    DateTime,
    ForeignKey,
    Numeric,
    JSON,
    Index,

)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from app.db.base import Base


class Payment(Base):
    __tablename__ = "payments"


    id: Mapped[int] = mapped_column(primary_key=True)

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        index=True,
    )

    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        default="BDT",
    )

    method: Mapped[str] = mapped_column(
        String(20),
    )
    # bkash | nagad | rocket

    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
    )
    # PENDING | SUCCESS | FAILED | REFUNDED

    transaction_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )

    gateway_payment_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    payment_metadata: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
    )

    clinic_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    clinic = relationship(
        "Clinic",
        back_populates="payments",
        lazy="selectin",
    )

    appointment = relationship("Appointment")
    patient = relationship("User")

    __table_args__ = (
        Index(
            "idx_unique_pending_payment",
            "appointment_id",
            unique=True,
            postgresql_where=(status == "PENDING"),
        ),
    )


Index("idx_payment_status", Payment.status)
Index("idx_payment_transaction", Payment.transaction_id)