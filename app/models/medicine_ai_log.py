from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base


class MedicineAILog(Base):

    __tablename__ = "medicine_ai_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    medicine_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "medicines.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    medicine_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    answer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    prompt_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    tokens_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )