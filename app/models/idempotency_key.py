from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time import UTC


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(primary_key=True)

    key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )

    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    response_body: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
    )

    status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_idempotency_user_key", "user_id", "key", unique=True),
    )