from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Numeric,
    JSON,
    Index,
    text

)
from decimal import Decimal
from sqlalchemy import Enum as SqlEnum

from app.models.enums.payment_status import (
    PaymentStatus,
)
from uuid import uuid4
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from app.db.base import Base


class Payment(Base):
    __tablename__ = "payments"


    id: Mapped[int] = mapped_column(primary_key=True)

    public_invoice_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid4()),
    )

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT"),
        index=True,
    )

    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(
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

    status: Mapped[PaymentStatus] = mapped_column(
        SqlEnum(
            PaymentStatus,
            name="payment_status",
        ),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    # PENDING | SUCCESS | FAILED | REFUNDED

    transaction_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )

    gateway_payment_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
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

    refunded_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )

    refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    refund_transaction_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )

    clinic_id: Mapped[int] = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="RESTRICT",   # or remove ondelete
        ),
        nullable=False,
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
            postgresql_where=text(
                "status = 'PENDING'"
            ),
        ),
    )


Index("idx_payment_status", Payment.status)
