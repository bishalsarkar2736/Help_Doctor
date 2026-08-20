from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    func,
    text,
    Enum as SQLEnum,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,relationship
)

from app.db.base import Base


class ClinicStatus(str, Enum):
    """Clinic lifecycle (platform-plane, super-admin controlled).

    Values equal names (project enum convention).
    """
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"   # temporarily disabled; users blocked from login
    DELETED = "DELETED"       # soft-deleted / archived (never hard-deleted)


class Clinic(Base):

    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    status: Mapped[ClinicStatus] = mapped_column(
        SQLEnum(ClinicStatus, name="clinic_status", create_type=False),
        default=ClinicStatus.ACTIVE,
        server_default="ACTIVE",
        nullable=False,
        index=True,
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        index=True,
        nullable=False,
    )

    # The tenant's DNS label — the "citycare" in citycare.example.com — used to
    # identify which clinic a request is for when routing by hostname.
    #
    # Nullable, and nullable on purpose: a clinic with no subdomain is simply
    # not reachable by hostname, which is every clinic today. Requiring one
    # would mean no clinic could be created before its DNS was decided.
    #
    # 63 characters is the DNS limit for a single label, not a product choice.
    # Stored already normalised (stripped, lowercased) — see
    # app/domain/clinics/subdomain.py for the rule and why each part of it
    # exists. Nothing routes on this column yet.
    subdomain: Mapped[str | None] = mapped_column(
        String(63),
        nullable=True,
    )

    # Declared after the column it indexes, so it can reference it directly.
    #
    # Clinic names are unique case-insensitively: "City Clinic" and "city
    # clinic" are the same clinic to everyone except a byte comparison. A
    # functional index cannot be expressed as unique=True on the column, so it
    # was written as raw SQL in a migration and never mirrored here — which
    # left autogenerate proposing to drop it, and duplicate clinic names
    # differing only in case becoming possible.
    __table_args__ = (
        Index(
            "uq_clinic_name_lower",
            func.lower(name),
            unique=True,
        ),
        # Subdomains are unique case-insensitively for the same reason names
        # are, but with a harder consequence: DNS does not distinguish case, so
        # two rows differing only in case would be two tenants claiming one
        # host. Written as a functional index rather than unique=True because
        # lower() cannot be expressed on the column — the same reason as above.
        #
        # NULLs are not compared by a Postgres unique index, so any number of
        # clinics may have no subdomain.
        Index(
            "uq_clinic_subdomain_lower",
            func.lower(subdomain),
            unique=True,
        ),
        # The format rule, restated in the database.
        #
        # app/domain/clinics/subdomain.py is the only writer today, so this is
        # redundant with it — deliberately. This value becomes a public
        # hostname, and a malformed one cannot be fixed by editing it later
        # once it has been handed out. A constraint here holds for a direct
        # SQL fix, a data import and a future code path that forgets to call
        # the validator.
        #
        # Reserved names are NOT enforced here: that list is a product
        # decision that will change, and changing it would mean a migration
        # plus a constraint that existing rows might already violate.
        CheckConstraint(
            "subdomain IS NULL OR subdomain ~ "
            "'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'",
            name="ck_clinics_subdomain_format",
        ),
    )

    logo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    phone: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    website: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    primary_color: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # IANA timezone name (e.g. "Asia/Dhaka"). Doctor availability is entered in
    # this local time; slots are generated / validated against it.
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="UTC",
        default="UTC",
    )

    # When the clinic is open, keyed by weekday as a string ("0".."6",
    # Monday=0 — the same convention as DoctorAvailability.day_of_week, so the
    # two are never read against different calendars).
    #
    #   {"0": [{"open": "09:00", "close": "13:00"},
    #          {"open": "16:00", "close": "21:00"}]}
    #
    # A list per day because closing for lunch is the normal pattern here. A
    # weekday that is absent, or maps to an empty list, means closed.
    #
    # This describes the PREMISES, and is separate from whether any doctor is
    # free: a clinic can be open with a full appointment book, or shut while a
    # doctor's availability rule still exists. "Are you open?" is answered from
    # here; "who can see me?" is answered from slots. They are not derived from
    # one another and may legitimately disagree.
    opening_hours: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        server_default=text("'{}'::json"),
        default=dict,
    )

    # Dates the clinic is closed regardless of opening_hours:
    #
    #   [{"date": "2026-03-26", "name": "Independence Day"}]
    #
    # Closures only. A day with different-but-open hours is a change to
    # opening_hours, not a holiday, so that "are you open?" never has to
    # reconcile two sources that both claim to say when the doors are open.
    holiday_schedule: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        server_default=text("'[]'::json"),
        default=list,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    doctors = relationship(
        "Doctor",
        back_populates="clinic",
        lazy="selectin",
    )

    appointments = relationship(
        "Appointment",
        back_populates="clinic",
        lazy="selectin",
    )

    prescriptions = relationship(
        "Prescription",
        back_populates="clinic",
        lazy="selectin",
    )

    payments = relationship(
        "Payment",
        back_populates="clinic",
        lazy="selectin",
    )

    admins = relationship(
        "User",
        back_populates="clinic",
        lazy="selectin",
    )