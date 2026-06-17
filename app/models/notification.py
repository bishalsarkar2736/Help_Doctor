from sqlalchemy import String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from app.db.base import Base
from sqlalchemy.dialects.postgresql import UUID
import uuid
from sqlalchemy import Index

from enum import Enum
from sqlalchemy import Enum as SQLEnum

class NotificationCategory(str, Enum):
    APPOINTMENT = "APPOINTMENT"
    PRESCRIPTION = "PRESCRIPTION"
    PAYMENT = "PAYMENT"
    SYSTEM = "SYSTEM"


class Notification(Base):
    __tablename__ = "notifications"

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "user_id",
            name="uq_notification_event_user",
        ),

        Index(
            "ix_notification_delivery_failed",
            "delivery_failed_at",
        ),

        Index(
            "ix_notification_email_delivered",
            "email_delivered_at",
        ),

        Index(
            "ix_notification_push_delivered",
            "push_delivered_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )

    title: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)

    related_appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    read_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    push_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    email_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    delivery_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    delivery_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


    category: Mapped[NotificationCategory] = mapped_column(
        SQLEnum(
            NotificationCategory,
            name="notification_category",
        ),
        nullable=False,
        server_default=NotificationCategory.SYSTEM.value,
    )
    
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User", lazy="joined")

    event = relationship("OutboxEvent")