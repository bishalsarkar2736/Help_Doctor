from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.core.time import UTC
from app.db.base import Base

TOKEN_TYPE_LINK = "LINK"
TOKEN_TYPE_OTP = "OTP"


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # Which credential this row holds. The two differ by ~236 bits of entropy
    # and MUST NOT be interchangeable: before this column existed, both lived
    # here indistinguishably, so the link endpoint's unthrottled global hash
    # lookup would happily match a 6-digit OTP and bypass every one of the
    # OTP's brute-force defences.
    #   LINK — token_urlsafe(32), emailed as a click-through link
    #   OTP  — 6-digit code, typed in by the user
    token_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        server_default=TOKEN_TYPE_LINK,
        index=True,
    )

    # Wide enough for an Argon2 hash (~97 chars), not just a 64-char SHA-256:
    # OTPs are stored with a real KDF because a bare SHA-256 of a 6-digit code
    # is reversible in under a second by anyone who reads this table.
    token_hash: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    used: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Failed OTP guesses. A 6-digit code is brute-forceable, so verification is
    # locked out once this hits MAX_OTP_ATTEMPTS.
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    user = relationship(
        "User",
        back_populates="email_verification_tokens",
    )