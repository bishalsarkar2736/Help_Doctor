from sqlalchemy import (
    Integer,
    String,
    DateTime,
)

from sqlalchemy.orm import mapped_column

from app.db.base import Base

from app.core.time import utc_now


class MedicineAssistantQuery(Base):

    __tablename__ = "medicine_assistant_queries"

    id = mapped_column(
        Integer,
        primary_key=True,
    )

    question = mapped_column(
        String(1000),
        nullable=False,
    )

    medicine_name = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    created_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )