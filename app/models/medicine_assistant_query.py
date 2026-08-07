from sqlalchemy import (
    Integer,
    String,
    DateTime,
    ForeignKey
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

    clinic_id = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    # The question a patient typed is deliberately NOT stored. A chat box
    # invites people to describe their health, and the surest way never to
    # mishandle that text is never to keep it. medicine_name below carries the
    # analytics signal — what was asked ABOUT — without the words.

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