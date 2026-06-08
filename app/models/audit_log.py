from datetime import datetime
from sqlalchemy import String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time import UTC


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)

    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True
    )

    action: Mapped[str | None] = mapped_column(String(50))

    resource: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(String(20), nullable=False)

    details: Mapped[dict | None] = mapped_column(JSON)

    request_id: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )