"""Who looked at which patient's data, and when.

Deliberately separate from `audit_logs`, which records **mutations** (login,
create, update, issue). This table records **reads** of protected health
information, which HIPAA-style regimes require and which the mutation trail by
definition cannot show: a clinician who opens a record and changes nothing
leaves no trace in an audit-of-changes.

Kept as its own table rather than folded into audit_logs because:

* Volume differs by orders of magnitude — reads vastly outnumber writes, and
  mixing them would bury the mutation trail.
* The compliance question is "who accessed patient X?", so patient_id has to be
  a first-class indexed column, not a key inside a JSON blob.
* Retention and export rules for access logs are usually distinct.

Rows are append-only. Nothing in the application updates or deletes them.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PHIResourceType:
    """What was looked at. Kept as constants so queries can rely on the values."""

    PATIENT_PROFILE = "patient_profile"
    MEDICAL_HISTORY = "medical_history"
    ALLERGIES = "allergies"
    PRESCRIPTION = "prescription"
    PRESCRIPTION_PDF = "prescription_pdf"
    PRESCRIPTION_LIST = "prescription_list"
    PATIENT_SEARCH = "patient_search"
    APPOINTMENT_RECORD = "appointment_record"


class PHIAction:
    VIEW = "view"
    LIST = "list"
    SEARCH = "search"
    DOWNLOAD = "download"


class PHIAccessLog(Base):

    __tablename__ = "phi_access_logs"

    # Index layout follows the measured query plans (see migration
    # b7c4a91e5d38). Every read goes through GET /admin/phi-access, which is
    # clinic-scoped and always filters clinic_id, so the composites lead with
    # clinic_id and end with created_at to match the ORDER BY.
    __table_args__ = (
        # "Everything that touched this patient, most recent first" — the
        # question a compliance officer or a patient exercising their right of
        # access actually asks.
        Index("ix_phi_access_patient_time", "patient_id", "created_at"),
        # "Everything this clinician looked at" — the insider-threat query.
        Index("ix_phi_access_actor_time", "actor_user_id", "created_at"),
        Index("ix_phi_access_clinic_time", "clinic_id", "created_at"),
        # The three filtered shapes the admin endpoint actually serves. Without
        # these the planner falls back to scanning the clinic's whole range and
        # discarding non-matching rows.
        Index("ix_phi_access_clinic_patient_time", "clinic_id", "patient_id", "created_at"),
        Index("ix_phi_access_clinic_actor_time", "clinic_id", "actor_user_id", "created_at"),
        Index("ix_phi_access_clinic_resource_time", "clinic_id", "resource_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- who ---
    # No ON DELETE CASCADE: an access record must outlive the account that made
    # it, otherwise deleting a user erases the evidence of what they read.
    # No standalone index: (actor_user_id) is an exact prefix of
    # ix_phi_access_actor_time, so a second one only costs writes.
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Denormalised on purpose. Roles change; the log must say what the actor
    # was AT THE TIME, not what they are now.
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)

    # Null for super_admin, who is not clinic-scoped.
    clinic_id: Mapped[int | None] = mapped_column(
        ForeignKey("clinics.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # --- whose data ---
    # References users.id, matching appointments.patient_id.
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # --- what ---
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)

    # Null for list/search, which have no single subject record.
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    action: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- when / correlation ---
    # Ties an access back to the HTTP request in the structured logs.
    #
    # Not indexed. Correlation runs the other way — you have a row here and go
    # look the id up in the logs — so nothing ever filters on this column. An
    # index on random UUIDs was the largest on the table and the most expensive
    # to maintain, on the hottest-write path in the system.
    request_id: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<PHIAccessLog actor={self.actor_user_id}({self.actor_role}) "
            f"{self.action}:{self.resource_type} patient={self.patient_id}>"
        )
