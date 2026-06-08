from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, JSON, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.db.base import Base


class PaymentAuditLog(Base):

    __tablename__ = "payment_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)

    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"),
        index=True,
    )

    gateway: Mapped[str] = mapped_column(String(20))

    event_type: Mapped[str] = mapped_column(String(50))

    payload: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )