import uuid
from datetime import datetime
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import String, JSON, DateTime, Integer, func,Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    __table_args__ = (
        Index(
            "ix_outbox_pending_retry",
            "status",
            "next_retry_at",
        ),
        # The dispatcher's main scan. Created by raw SQL in a migration and
        # never mirrored here, so autogenerate wanted to drop it -- which would
        # have turned the outbox poll into a sequential scan that degrades as
        # the table grows, with nothing failing to say so.
        Index(
            "idx_outbox_ready_v2",
            "status",
            "failed_at",
            "next_retry_at",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
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

    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        index=True,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
       
    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=5,
    )

    
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
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

    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    