import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, JSON, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        index=True
    )

    payload: Mapped[dict] = mapped_column(
        JSON
    )

    is_processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    