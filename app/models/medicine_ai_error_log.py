from datetime import datetime

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    func,
    ForeignKey
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base


class MedicineAIErrorLog(Base):

    __tablename__ = "medicine_ai_error_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    medicine_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    clinic_id: Mapped[int] = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )