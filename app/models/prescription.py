from __future__ import annotations
from typing import TYPE_CHECKING
from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, Integer, DateTime,Enum,Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from app.core.time import utc_now
import uuid
from sqlalchemy.dialects.postgresql import UUID
import enum

if TYPE_CHECKING:
    from app.models.doctor import Doctor
    from app.models.user import User

    from app.models.appointment import Appointment



class PrescriptionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)

    uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
        nullable=False,
        default=uuid.uuid4,
        index=True,
    )

    parent_prescription_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "prescriptions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    revision_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    is_latest_revision: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    patient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    status: Mapped[PrescriptionStatus] = mapped_column(
        Enum(PrescriptionStatus),
        default=PrescriptionStatus.DRAFT,
        nullable=False,
    )

    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Why an allergy warning was prescribed through, kept on the record it
    # justifies. The audit log also holds it, but that trail is append-only and
    # subject to retention purging — a safety rule must not depend on log
    # retention, and a clinician reading the prescription should be able to see
    # the justification without a database administrator.
    #
    # NOT exposed on PrescriptionResponse: that schema is what GET
    # /prescriptions/me returns to patients, and this is a clinical note
    # between prescriber and record.
    allergy_override_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # The active substances the reason above covers.
    #
    # Substances, not typed medicine names: relabelling "Cefim" to
    # "Cefim 400mg", or switching to another brand of the same generic, is not
    # a new clinical decision, and comparing typed strings would demand a fresh
    # justification for a judgement that has not changed.
    allergy_override_substances: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    clinic_id: Mapped[int] = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="RESTRICT",   # or remove ondelete
        ),
        nullable=False,
        index=True,
    )

    clinic = relationship(
        "Clinic",
        lazy="selectin",
    )


    # ====================================
    # RELATIONSHIPS
    # ====================================

    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
        foreign_keys=[doctor_id],
        back_populates="doctor_prescriptions",
        lazy="selectin",
    )

    patient: Mapped["User"] = relationship(
        "User",
        foreign_keys=[patient_id],
        back_populates="patient_prescriptions",
        lazy="selectin",
    )

    appointment: Mapped["Appointment"] = relationship(
        "Appointment",
        foreign_keys=[appointment_id],
        back_populates="prescription",
        lazy="selectin",
    )

    items: Mapped[list["PrescriptionItem"]] = relationship(
        "PrescriptionItem",
        back_populates="prescription",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ====================================
    # REVISION RELATIONSHIPS
    # ====================================

    parent_prescription: Mapped["Prescription | None"] = relationship(
        "Prescription",
        remote_side=[id],
        back_populates="revisions",
    )

    revisions: Mapped[list["Prescription"]] = relationship(
        "Prescription",
        back_populates="parent_prescription",
    )


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    prescription_id: Mapped[int] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"),
        nullable=False, index=True)

    # What the prescriber actually wrote. Stays the record of the prescription
    # even if the catalogue entry is later renamed or removed, so it is never
    # derived from medicine_id.
    medicine_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # The catalogue entry the prescriber picked, when they picked one.
    #
    # Nullable on purpose: prescribing accepts free text (a medicine the
    # catalogue does not carry must still be prescribable), and every row
    # written before autocomplete existed has no link. Where it IS set, allergy
    # checking uses it instead of matching the typed string, which removes the
    # guesswork entirely.
    #
    # SET NULL rather than RESTRICT: a prescription is a clinical record and
    # must survive catalogue cleanup. Losing the link degrades allergy checking
    # back to name matching; blocking the delete would make the catalogue
    # effectively immutable.
    medicine_id: Mapped[int | None] = mapped_column(
        ForeignKey("medicines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    dosage: Mapped[str | None] = mapped_column(String(100))

    frequency: Mapped[str | None] = mapped_column(String(100))

    duration_days: Mapped[int | None] = mapped_column(Integer)

    instructions: Mapped[str | None] = mapped_column(Text)

    prescription: Mapped["Prescription"] = relationship(
        "Prescription",
        back_populates="items",
    )