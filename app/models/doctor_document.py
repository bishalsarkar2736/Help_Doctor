from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DoctorDocumentType(str, Enum):
    """Credential evidence a clinic admin reviews before approving a doctor.

    Values equal names (project enum convention).
    """
    BMDC_CERTIFICATE = "BMDC_CERTIFICATE"
    DEGREE = "DEGREE"
    LICENSE = "LICENSE"
    OTHER = "OTHER"


class DoctorDocument(Base):
    __tablename__ = "doctor_documents"

    id: Mapped[int] = mapped_column(primary_key=True)

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    doc_type: Mapped[DoctorDocumentType] = mapped_column(
        SQLEnum(
            DoctorDocumentType,
            name="doctor_document_type",
            create_type=False,
        ),
        nullable=False,
    )

    # Stored path on disk (see the horizontal-scaling caveat in DEPLOYMENT.md —
    # object storage is the production answer).
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)

    original_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    content_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    doctor = relationship("Doctor", back_populates="documents")
