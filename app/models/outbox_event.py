import uuid
from datetime import datetime
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import String, JSON, DateTime, Integer, func,Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class OutboxStatus:
    """The outbox lifecycle, spelled once.

    LOWERCASE, and that is not arbitrary. The column carries default="pending"
    and server_default="pending", the database column default is 'pending', and
    every status the worker writes or selects on is lowercase. So lowercase is
    what the system already means; this only gives it a name.

    Why a name at all: the worker matched `status == "pending"` while several test
    fixtures constructed events with "PENDING". Those events are invisible to
    process_batch — its WHERE clause simply never matches them — so a test built
    on one asserts nothing at all, silently. A typed literal cannot be caught by
    a type checker; a constant can at least be grepped, and is checked by a test
    below.

    Plain strings rather than an Enum, deliberately. The column is String(20); a
    str-subclassing Enum binds correctly today but makes what reaches the driver
    depend on the Python version's str-Enum semantics, and a SQLAlchemy Enum type
    would mean a Postgres enum and a migration. Neither buys anything here.

    THE LIFECYCLE
        pending     published, not yet claimed. The state publish_event leaves
                    behind, via the column default.
        processing  claimed by a worker; processing_started_at is set, and a row
                    stuck here past PROCESSING_TIMEOUT is recovered to pending.
        processed   handled successfully, or skipped as unsupported.
        failed      terminal. Set on a non-retryable error and on exhausting
                    max_retries; failed_at is set with it, and the payload is
                    copied to a DeadLetterEvent row for replay.

    A retry is NOT a state: a retryable failure leaves the row `pending` with
    next_retry_at in the future, which is what the dispatcher's index is built on.
    There is deliberately no "dead" status — the dead-letter record lives in its
    own table and the original stays `failed`.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"

    ALL = frozenset({PENDING, PROCESSING, PROCESSED, FAILED})


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
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING,
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

    