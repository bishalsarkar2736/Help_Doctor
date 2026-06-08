import uuid
from datetime import datetime

from sqlalchemy import String, JSON, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # ❗ No FK (intentional)
    original_event_id: Mapped[uuid.UUID] = mapped_column(
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )

    payload: Mapped[dict] = mapped_column(
        JSON,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
    )

    max_retries: Mapped[int] = mapped_column(
        Integer,
    )

    error_message: Mapped[str] = mapped_column(
        String(500),
    )

    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )