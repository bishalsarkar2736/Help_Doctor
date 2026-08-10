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

        # The index every read of this table needs, and did not have.
        #
        # user_id had a foreign key but no index — Postgres does not create one
        # for an FK — and the only index containing it,
        # uq_notification_event_user, leads with event_id, so it cannot serve
        # `WHERE user_id = ?`. Listing a user's notifications, counting their
        # unread and syncing were all sequential scans of the whole table.
        #
        # Composite because the list query is
        #   WHERE user_id = ? [AND read_at ... ] [AND category = ...]
        #   ORDER BY created_at DESC LIMIT ? OFFSET ?
        # so leading on user_id and continuing on created_at satisfies the
        # filter AND the ordering from one index scan, with no sort step.
        #
        # Stored ascending on purpose. A btree can be scanned backwards at the
        # same cost, so ORDER BY created_at DESC is served by this index as it
        # stands; declaring DESC would add an expression index that alembic
        # compares unreliably for no gain.
        #
        # The unread count and mark-all-read (user_id = ? AND read_at IS NULL)
        # use the user_id prefix and filter read_at from the heap. /sync
        # (user_id = ?, ORDER BY id) uses the prefix and sorts a single user's
        # rows. Both are bounded by one user instead of the whole table, which
        # is the difference that mattered; a partial or (user_id, id) index for
        # either would be speculative until their plans say otherwise.
        Index(
            "ix_notifications_user_id_created_at",
            "user_id",
            "created_at",
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
            "ix_notification_email_failed",
            "email_failed_at",
        ),

        Index(
            "ix_notification_push_delivered",
            "push_delivered_at",
        ),
        Index(
            "ix_notification_whatsapp_delivered",
            "whatsapp_delivered_at",
        ),

        Index(
            "ix_notification_whatsapp_failed",
            "whatsapp_failed_at",
        )
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )

    title: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)

    related_appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True, index=True)

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

    # Realtime is a delivery channel like the others and now records its own
    # timestamp.
    #
    # It used to write ONLY the aggregate delivered_at, guarded on that column
    # being NULL — so if push or email had already delivered, a realtime
    # acknowledgement was discarded and nothing recorded that the socket
    # received it. This column is added because that information was being
    # lost, not for symmetry: without it the aggregate cannot be explained by
    # the per-channel columns.
    realtime_delivered_at: Mapped[datetime | None] = mapped_column(
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

    email_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    email_error: Mapped[str | None] = mapped_column(
        Text,
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

    whatsapp_delivered_at : Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    whatsapp_failed_at : Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    whatsapp_error : Mapped[str | None]= mapped_column(
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
    
    # RESTRICT, not CASCADE.
    #
    # Under CASCADE, deleting an outbox event deleted its notifications with it.
    # Nothing deletes outbox events today, so nothing was lost — but the
    # notification retention job establishes the pattern, and the first outbox
    # retention job written to match it would have silently taken the
    # notification history along. Silently: a purge that deletes more than it
    # was asked to raises nothing and logs nothing.
    #
    # SET NULL was considered and ruled out on evidence rather than taste. This
    # column is NOT NULL, so it would have to become nullable — and
    # uq_notification_event_user is (event_id, user_id), where Postgres treats
    # NULLs as distinct. Nullable event_id would therefore stop deduplicating
    # notifications, trading a retention risk for a correctness one.
    #
    # RESTRICT changes nothing about current behaviour and makes a future purge
    # fail loudly instead of quietly: the DELETE errors, the operator sees it,
    # and they decide what should happen to the notifications rather than
    # discovering afterwards that it happened for them.
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="RESTRICT"),
        nullable=False,
    )

    user = relationship("User", lazy="joined")

    event = relationship("OutboxEvent")