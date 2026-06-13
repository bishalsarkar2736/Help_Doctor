from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    Text,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base


class ActivityLog(Base):

    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    clinic_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )

    entity_type: Mapped[str] = mapped_column(
        String(50),
        index=True,
    )

    entity_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )