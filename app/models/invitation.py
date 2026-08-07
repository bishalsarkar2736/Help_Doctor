from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import UTC
from app.db.base import Base
from app.models.user import UserRole


class InvitationStatus(str, Enum):
    # Values equal names (matches the project's PaymentStatus convention),
    # so DB labels are unambiguous.
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"


class Invitation(Base):
    """A hashed-token invitation to join a specific clinic with a staff role.

    Secure-bootstrap chain:
        Super Admin -> invites first Clinic Admin (role=admin)
        Clinic Admin -> invites Receptionist / Doctor (their clinic only)

    Multi-clinic ready: each invitation targets exactly one `clinic_id`, which
    maps cleanly onto a future `doctor_clinics` membership row — a doctor can
    receive (and accept) invitations to several clinics over time without any
    schema change here.
    """

    __tablename__ = "invitations"

    # No index=True: a primary key already has a unique index, and asking
    # for a second one only costs writes. The database never had it, so
    # autogenerate kept proposing to create it.
    id: Mapped[int] = mapped_column(primary_key=True)

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    # Reuses the existing `user_roles` enum type. Only staff roles are ever
    # stored here (admin / receptionist / doctor) — never patient/super_admin.
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, name="user_roles", create_type=False),
        nullable=False,
    )

    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Only the SHA-256 hash of the token is stored; the raw token is emailed.
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )

    status: Mapped[InvitationStatus] = mapped_column(
        SQLEnum(
            InvitationStatus,
            name="invitation_status",
            create_type=False,
        ),
        default=InvitationStatus.PENDING,
        nullable=False,
        index=True,
    )

    invited_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)

    accepted_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Invitation email={self.email} role={self.role} "
            f"clinic_id={self.clinic_id} status={self.status}>"
        )
