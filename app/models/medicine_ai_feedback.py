from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    func,
    UniqueConstraint,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.base import Base



class MedicineAIFeedback(Base):

    __tablename__ = "medicine_ai_feedback"

    __table_args__ = (
        UniqueConstraint(
            "ai_log_id",
            name="uq_medicine_ai_feedback_ai_log_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    ai_log_id: Mapped[int] = mapped_column(
        ForeignKey(
            "medicine_ai_logs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    helpful: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )