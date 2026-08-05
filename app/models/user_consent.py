"""Who accepted which legal document, at which version, and when.

This is the evidence. "The user agreed to our terms" is not a defensible claim
without a record of WHICH wording they were shown and WHEN — a policy that has
been revised three times since makes an undated acceptance worthless.

Append-only. Nothing in the application updates or deletes a consent row: a
withdrawal or a re-acceptance is a NEW row, so the history stays readable.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserConsent(Base):

    __tablename__ = "user_consents"

    __table_args__ = (
        # One row per user per document per version. Re-submitting the same
        # acceptance (a double-clicked signup, a retried request) must not
        # produce duplicate evidence that looks like two separate agreements.
        UniqueConstraint(
            "user_id", "document", "version", name="uq_user_consent_version"
        ),
        # "What has this user agreed to?" — the question asked when handling a
        # data request or a dispute.
        Index("ix_user_consent_user_document", "user_id", "document"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # No CASCADE: a consent record must outlive attempts to remove the account,
    # for the same reason phi_access_logs does. Deleting a user should not erase
    # the evidence of what they agreed to.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # "terms" | "privacy" — see app/legal/documents.py
    document: Mapped[str] = mapped_column(String(32), nullable=False)

    # The version as published at the moment of acceptance, e.g. "2026-08-01".
    # Stored, never derived: the current version will change, and this row must
    # keep pointing at what the user was actually shown.
    version: Mapped[str] = mapped_column(String(32), nullable=False)

    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Circumstantial detail, both nullable: useful when an acceptance is
    # disputed, but never required for the record to be valid. A user behind a
    # proxy or a client that sends no user agent still gave consent.
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UserConsent user={self.user_id} {self.document}"
            f"@{self.version}>"
        )
