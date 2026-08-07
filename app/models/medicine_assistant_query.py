from sqlalchemy import (
    Index,
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

    # What was asked for, and how it went. Together these answer what the
    # removed question text was really being read for — refusal rate, which
    # fields are asked for and empty, whether a rising not_found rate is a gap
    # in the catalogue or in its aliases — without anyone's sentence.
    #
    # Nullable because v1 writes neither while the two assistants run side by
    # side.
    intent = mapped_column(String(40), nullable=True)
    status = mapped_column(String(20), nullable=True)

    # Reporting scans these two together. Created by raw SQL in a migration
    # and never declared, so autogenerate wanted to drop it.
    __table_args__ = (
        Index(
            "ix_medicine_assistant_queries_intent_status",
            "intent",
            "status",
        ),
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