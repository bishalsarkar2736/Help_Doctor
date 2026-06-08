from datetime import datetime
from typing import Dict, Any

from sqlalchemy import ForeignKey, Text, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # ✅ CRITICAL: prevents duplicate subscriptions
    endpoint: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
    )

    keys: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )